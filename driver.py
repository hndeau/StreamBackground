import datetime
import json
import logging
import sys
import threading
import time
import aiohttp
import keyboard
import queue
import asyncio
from screeninfo import get_monitors
from selenium import webdriver
from selenium.webdriver import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from concurrent.futures import ThreadPoolExecutor

from utility_helpers import load_from_json, save_to_json

# --------- CONFIG AND INITIALIZATION -----------

with open("config.json", "r") as file:
    config = json.load(file)

DEBUG_MODE = "--debug" in sys.argv or "-d" in sys.argv
API_KEY = config['API_KEY']

if not API_KEY:
    logging.error("API key not provided in config.")
    sys.exit(1)

BASE_URL = config['BASE_URL']
CHANNEL_ID = config['CHANNEL_ID']
BROWSER_WINDOW_SIZE = tuple(config['BROWSER_WINDOW_SIZE'])

# Custom log levels
DEBUG_GENERAL = 25
DEBUG_SELENIUM = 15
logging.addLevelName(DEBUG_GENERAL, "DEBUG_GENERAL")
logging.addLevelName(DEBUG_SELENIUM, "DEBUG_SELENIUM")


# --------- DEBUG HELPERS ---------

def debug_general(self, message, *args, **kwargs):
    self.log(DEBUG_GENERAL, message, *args, **kwargs)


def debug_selenium(self, message, *args, **kwargs):
    self.log(DEBUG_SELENIUM, message, *args, **kwargs)


# ---------------------------------
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logging.Logger.debug_general = debug_general
logging.Logger.debug_selenium = debug_selenium

# Set up log level based on command-line arguments
if "--debug" in sys.argv:
    logging_level = DEBUG_GENERAL
elif "--debug-full" in sys.argv:
    logging_level = DEBUG_SELENIUM
else:
    logging_level = logging.WARNING

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging_level)

VIDEO_CACHE = load_from_json() or {}
TOP_N = config.get('TOP_N', 100)  # default to 100 if not specified in config


# --------- MONITOR AND BROWSER HANDLING ---------
class Monitor:
    def __init__(self, browser, url=None):
        self.browser = browser
        self.current_url = url

    def is_playing_video(self):
        if self.is_page_loaded():
            return self._video_has_ended()
        return False

    def play_video(self, url):
        try:
            logger.debug_general(f'Video Started: {url}')  # Debug statement for video play
            self.browser.get(url)
            self.current_url = url
            player = WebDriverWait(self.browser, 15).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "video.video-stream"))
            )
            player.send_keys('F')
            player.send_keys(Keys.SPACE)
        except Exception as e:
            logger.error(f"Error playing video: {e}")

    def close(self):
        self.browser.quit()

    def is_page_loaded(self):
        """Check if the page is completely loaded."""
        try:
            return self.browser.execute_script("return document.readyState") == "complete"
        except Exception as e:
            logger.error(f"Error checking page load status: {e}")
            return False

    def _video_has_ended(self):
        try:
            player = WebDriverWait(self.browser, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "video.video-stream"))
            )
            script = "return arguments[0].paused"
            is_paused = self.browser.execute_script(script, player)
            return not is_paused
        except Exception as e:
            logger.error(f"Error checking video status: {e}")
            return False


class MonitorManager:
    def __init__(self, live_videos, top_videos):
        self.monitors = []
        self.STOP_THREADS = False
        self.video_queue = queue.PriorityQueue()
        self.live_videos = live_videos
        self.top_videos = top_videos
        self.next_page_token = None  # Initialize next_page_token
        self.enqueue_videos(self.live_videos, self.top_videos)

    def is_stopped(self):
        return self.STOP_THREADS

    def stop(self):
        self.STOP_THREADS = True
        # Pause for a brief moment to allow any ongoing operations to complete
        time.sleep(2)
        self.cleanup_browsers()

    def cleanup_browsers(self):
        """Close all browser windows."""
        for monitor in self.monitors:
            monitor.close()

    async def fetch_next_videos(self):
        # Fetch the next set of top videos, bypassing the cache
        next_top_videos, self.next_page_token = await fetch_videos(order='viewCount', max_results=TOP_N,
                                                                   page_token=self.next_page_token, bypass_cache=True)
        # Properly handle the next_page_token
        if self.next_page_token != -1:  # Check if there's a next page
            for next_top_video in next_top_videos:
                if next_top_video not in self.top_videos:  # Check if the video URL is unique
                    self.video_queue.put((1, next_top_video))  # Enqueue top videos with priority 1
                    self.top_videos.append(next_top_video)  # Append next_top_video to the top_videos list
        # Update the cache with the appended top_videos
        save_to_json({
            'last_updated': datetime.datetime.now().strftime('%Y-%m-%d'),
            'urls': self.top_videos,
            'last_page_token': self.next_page_token  # Save the next page token instead of the last one
        }, key='viewCount')  # Save to cache with the key 'viewCount' (or appropriate key for top videos)
        return next_top_videos

    async def monitor_video_statuses(self, monitor):
        while not self.is_stopped():
            if monitor.is_page_loaded() and not monitor.is_playing_video():
                # Check the first item in the priority queue (without removing it)
                priority, video_url = self.video_queue.queue[0] if not self.video_queue.empty() else (None, None)

                # If it's a live stream and it's not already playing on this monitor, then play it
                if priority == 0 and video_url != monitor.current_url:
                    logger.debug_general(f"Stream detected, switching...")
                    self.video_queue.get()  # Dequeue the live stream from the priority queue
                    monitor.play_video(video_url)
                else:
                    if self.video_queue.empty():
                        await self.fetch_next_videos()  # Fetch and enqueue next set of videos if queue is empty
                    priority, video_url = self.video_queue.get()  # Dequeue next video
                    if video_url != monitor.current_url:  # Avoid replaying the same video
                        monitor.play_video(video_url)
            await asyncio.sleep(5)

    async def enqueue_next_videos(self):
        next_top_videos = await self.fetch_next_videos()
        for next_top_video in next_top_videos:
            self.video_queue.put((1, next_top_video))  # Enqueue top videos with priority 1

    async def fetch_all_videos(self):
        return self.live_videos, self.top_videos

    def enqueue_videos(self, live_videos, top_videos):
        for live_video in live_videos:
            self.video_queue.put((0, live_video))  # Enqueue live videos with priority 0

        for top_video in top_videos:
            self.video_queue.put((1, top_video))  # Enqueue top videos with priority 1
        # Load viewCount cache and extract the last page token
        view_count_cache = load_from_json().get('viewCount', {})
        self.next_page_token = view_count_cache.get('last_page_token', None)

    def init_browser_and_return_monitor(self, monitor):
        """This method initializes the browser and returns the monitor instance."""
        browser = webdriver.Firefox()
        logger.debug_selenium('Browser window opened')
        screen_width, screen_height = monitor.width, monitor.height
        window_width, window_height = BROWSER_WINDOW_SIZE
        position_x = (screen_width - window_width) // 2 + monitor.x
        position_y = (screen_height - window_height) // 2 + monitor.y

        browser.set_window_size(*BROWSER_WINDOW_SIZE)
        browser.set_window_position(position_x, position_y)

        monitor_instance = Monitor(browser)
        self.monitors.append(monitor_instance)
        logger.debug_general(f'Browser initialized on monitor with position: x={position_x}, y={position_y}')
        return monitor_instance

    async def monitor_all_screens(self):
        detected_monitors = get_monitors()

        # Use ThreadPoolExecutor to initialize browsers in parallel
        with ThreadPoolExecutor(max_workers=len(detected_monitors)) as executor:
            initialized_monitors = list(executor.map(self.init_browser_and_return_monitor, detected_monitors))

        # Once all browsers are initialized, start the asynchronous monitoring
        await self.monitor_video_statuses_on_all_monitors(initialized_monitors)

    async def monitor_video_statuses_on_all_monitors(self, initialized_monitors):
        await asyncio.gather(*[self.monitor_video_statuses(monitor) for monitor in initialized_monitors])

    def key_listener(self):
        keyboard.wait('esc')
        self.stop()


# -------- YOUTUBE API HANDLING -----------
async def fetch_videos(event_type=None, order=None, max_results=None, page_token=None, bypass_cache=False):
    cache_key = event_type or order
    if not bypass_cache and cache_key in VIDEO_CACHE and 'last_updated' in VIDEO_CACHE[cache_key]:
        last_updated = datetime.datetime.strptime(VIDEO_CACHE[cache_key]['last_updated'], '%Y-%m-%d')
        caching_time = 1 if cache_key == 'live' else 60
        if (datetime.datetime.now() - last_updated).days < caching_time:
            logger.debug_general(
                f"Using cached {cache_key} videos. Last updated on {VIDEO_CACHE[cache_key]['last_updated']}")
            return VIDEO_CACHE[cache_key]['urls'], page_token

    params = {
        'part': 'id',
        'channelId': CHANNEL_ID,
        'type': 'video',
        'key': API_KEY
    }

    if event_type == 'live':
        params['eventType'] = 'live'
        params['order'] = order if order else 'viewCount'  # Default to viewCount if order is not specified
    else:
        if order:
            params['order'] = order

    if max_results:
        params['maxResults'] = max_results

    if page_token:
        params['pageToken'] = page_token

    if event_type:
        logger.debug_general(f"Making API call to fetch {event_type} videos.")
    else:
        logger.debug_general(f"Making API call to fetch videos with order: {order}.")

    async with aiohttp.ClientSession() as session:
        async with session.get(BASE_URL, params=params) as response:
            data = await response.text()
            json_data = json.loads(data)
            next_page_token = json_data.get('nextPageToken', -1)
            urls = ["https://www.youtube.com/embed/" + item['id']['videoId'] for item in json_data['items']]

    # Update the cache and save it
    # Update the cache and save it
    data_to_save = {
        'last_updated': datetime.datetime.now().strftime('%Y-%m-%d'),
        'urls': urls,
        'last_page_token': page_token  # Save the last page token
    }
    cache_key = event_type or order
    save_to_json(data_to_save, key=cache_key)
    return urls, next_page_token


async def fetch_live_videos():
    return await fetch_videos(event_type='live')


async def fetch_top_100_videos():
    return await fetch_videos(order='viewCount', max_results=TOP_N)


# ---------- MAIN EXECUTION FUNCTIONS ------------

async def fetch_videos_and_initialize_manager():
    live_videos, _ = await fetch_live_videos()  # This line expects two values
    top_videos, _ = await fetch_top_100_videos()  # This line expects two values
    return MonitorManager(live_videos, top_videos)


if __name__ == "__main__":
    manager = asyncio.run(fetch_videos_and_initialize_manager())

    # Start the key listener thread first
    key_thread = threading.Thread(target=manager.key_listener)
    key_thread.start()

    try:
        asyncio.run(manager.monitor_all_screens())
    finally:
        key_thread.join()
