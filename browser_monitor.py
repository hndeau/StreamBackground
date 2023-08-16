import asyncio
import threading

import keyboard
import time
import queue
import datetime
import json
import logging
import sys
import aiohttp
from screeninfo import get_monitors
from selenium import webdriver
from selenium.webdriver import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait
from concurrent.futures import ThreadPoolExecutor

from streamScrape import monitor_youtube_streams
from utility_helpers import load_from_json, save_to_json

# -------- LOGGING -----------
def load_config():
    with open("config.json", "r") as file:
        c = json.load(file)

    debug_mode = "--debug" in sys.argv or "-d" in sys.argv
    return c, debug_mode


def setup_logging():
    debug_general = 25
    debug_selenium = 15
    logging.addLevelName(debug_general, "debug_general")
    logging.addLevelName(debug_selenium, "debug_selenium")

    if "--debug" in sys.argv:
        logging_level = debug_general
    elif "--debug-full" in sys.argv:
        logging_level = debug_selenium
    else:
        logging_level = logging.WARNING

    logging.basicConfig(level=logging_level)

    logging.Logger.debug_general = lambda self, message, *args, **kwargs: self.log(debug_general, message, *args,
                                                                                   **kwargs)
    logging.Logger.debug_selenium = lambda self, message, *args, **kwargs: self.log(debug_selenium, message, *args,
                                                                                    **kwargs)

    return logging.getLogger(__name__)


if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

config, DEBUG_MODE = load_config()
logger = setup_logging()

API_KEY = config['API_KEY']
if not API_KEY:
    logging.error("API key not provided in config.")
    sys.exit(1)

BASE_URL = config['BASE_URL']
CHANNEL_ID = config['CHANNEL_ID']
CHANNEL = config['CHANNEL']
BROWSER_WINDOW_SIZE = tuple(config['BROWSER_WINDOW_SIZE'])
LIVE_VIDEOS_LIMIT = config.get('LIVE_VIDEOS_LIMIT', 10)
VIDEO_CACHE = load_from_json() or {}
POPULAR_VIDEOS_LIMIT = config.get('POPULAR_VIDEOS_LIMIT', 100)


# -------- MONITOR AND BROWSER HANDLING -----------
class Monitor:
    def __init__(self, browser, url=None):
        self.browser = browser
        self.current_url = url

    def play_video(self, url):
        if self.current_url == url:  # Prevent replaying the same video
            return
        try:
            logger.debug_general(f'Video Started: {url}')
            self.browser.get(url)
            self.current_url = url
            player = WebDriverWait(self.browser, 4).until(  # can probably be lower
                ec.element_to_be_clickable((By.CSS_SELECTOR, "video.video-stream"))
            )
            player.send_keys('F', Keys.SPACE)
        except Exception as e:
            logger.error(f"Error playing video: {e}")

    def close(self):
        self.browser.quit()

    def is_page_loaded(self):
        try:
            return self.browser.execute_script("return document.readyState") == "complete"
        except Exception as e:
            logger.error(f"Error checking page load status: {e}")
            return False

    def is_playing_video(self):
        try:
            # Wait for the video player element to be present on the page
            WebDriverWait(self.browser, 4).until(  # can probably be lower
                ec.presence_of_element_located((By.CSS_SELECTOR, "video.video-stream"))
            )
            player = self.browser.find_element(By.CSS_SELECTOR, "video.video-stream")
            return not self.browser.execute_script("return arguments[0].paused", player)
        except Exception as e:
            logger.debug(f"Failed to check page status\nWindow: {self.current_url}")
            return False


class MonitorManager:
    def __init__(self, live_videos, top_videos):
        self.prev_count = len(load_from_json().get('live', {}).get('urls', []))
        self.monitors = []
        self.STOP_THREADS = False
        self.video_queue = queue.PriorityQueue()
        self.live_videos = live_videos
        self.top_videos = top_videos
        self.active_videos = set()  # Create a set of active videos
        self.enqueue_videos(live_videos, top_videos)

        # Loading the tokens from the cache
        view_count_cache = load_from_json().get('viewCount', {})
        live_video_cache = load_from_json().get('live', {})
        self.next_popular_page_token = view_count_cache.get('last_page_token', None)
        self.live_next_page_token = live_video_cache.get('last_page_token', None)

    def is_stopped(self):
        return self.STOP_THREADS

    def stop(self):
        self.STOP_THREADS = True
        time.sleep(2)  # Pause for a brief moment to allow any ongoing operations to complete
        self.cleanup_browsers()
        self.active_videos.clear()  # Clear active_videos

    def cleanup_browsers(self):
        """Close all browser windows."""
        for monitor in self.monitors:
            monitor.close()

    def play_video_in_monitor(self, monitor):
        while not self.is_stopped():
            if monitor.is_page_loaded():
                if not monitor.is_playing_video():
                    priority, video_url = self.video_queue.get() if not self.video_queue.empty() else (None, None)
                    if priority is not None and video_url != monitor.current_url:
                        self.active_videos.add(video_url)  # Add the video to active_videos
                        monitor.play_video(video_url)
                        if monitor.current_url:  # Remove the previously playing video from active_videos
                            self.active_videos.discard(monitor.current_url)
            time.sleep(5)

    def enqueue_videos(self, live_videos, top_videos):  # Might be broken now
        for video, priority in zip(live_videos + top_videos, [0] * len(live_videos) + [1] * len(top_videos)):
            if video not in self.active_videos:
                self.video_queue.put((priority, video))

    def init_browser_and_return_monitor(self, monitor):
        """This method initializes the browser and returns the monitor instance."""
        options = Options()

        # Disable images
        options.set_preference('permissions.default.image', 2)
        # Disable CSS
        options.set_preference('permissions.default.stylesheet', 2)

        browser = webdriver.Firefox(options=options)
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

    async def fetch_next_live_videos(self):
        next_live_videos, _ = \
            await fetch_videos(event_type='live',
                               max_results=LIVE_VIDEOS_LIMIT,
                               page_token=None,
                               bypass_cache=True)
        for next_live_video in next_live_videos:
            self.video_queue.put((0, next_live_video))
        self.live_videos = next_live_videos
        self.prev_count = len(next_live_videos)

    async def fetch_and_enqueue_next_videos(self):
        while not self.is_stopped():
            result = await asyncio.get_running_loop().run_in_executor(None, monitor_youtube_streams, CHANNEL)
            if result > self.prev_count:
                await self.fetch_next_live_videos()  # Fetch next set of live videos
                self.enqueue_videos(self.live_videos, self.top_videos)  # Re-enqueue videos with updated live streams
            elif self.video_queue.empty() and self.next_popular_page_token != -1:
                next_top_videos, self.next_popular_page_token = \
                    await fetch_videos(order='viewCount',
                                       max_results=POPULAR_VIDEOS_LIMIT,
                                       page_token=self.next_popular_page_token,
                                       bypass_cache=True)
                for next_top_video in next_top_videos:
                    self.video_queue.put((1, next_top_video))
            await asyncio.sleep(5)

    async def monitor_all_screens(self):
        detected_monitors = get_monitors()
        with ThreadPoolExecutor(max_workers=len(detected_monitors)) as executor:
            initialized_monitors = list(executor.map(self.init_browser_and_return_monitor, detected_monitors))

        monitor_threads = [threading.Thread(target=self.play_video_in_monitor, args=(monitor,)) for monitor in
                           initialized_monitors]
        for t in monitor_threads:
            t.start()

        await self.fetch_and_enqueue_next_videos()  # Simply await the coroutine

        for t in monitor_threads:
            t.join()

    async def monitor_video_statuses_on_all_monitors(self, initialized_monitors):
        monitor_tasks = [self.play_video_in_monitor(monitor) for monitor in initialized_monitors]
        await asyncio.gather(*monitor_tasks)

    def key_listener(self):
        keyboard.wait('esc')
        self.stop()


# -------- YOUTUBE API HANDLING -----------
async def fetch_videos(event_type=None, order=None, max_results=None, page_token=None, bypass_cache=False):
    cache_key = event_type or order
    # Check cache
    if not bypass_cache and cache_key in VIDEO_CACHE and 'last_updated' in VIDEO_CACHE[cache_key]:
        last_updated = datetime.datetime.strptime(VIDEO_CACHE[cache_key]['last_updated'], '%Y-%m-%d')
        caching_time = 1 if cache_key == 'live' else 60
        if (datetime.datetime.now() - last_updated).days < caching_time:
            logger.debug_general(
                f"Using cached {'popular' if cache_key == 'viewCount' else cache_key} videos. "
                f"Last updated on {VIDEO_CACHE[cache_key]['last_updated']}")
            return VIDEO_CACHE[cache_key]['urls'], page_token

    # Cache is invalid/inaccurate/bypassed
    params = {
        'part': 'id',
        'channelId': CHANNEL_ID,
        'type': 'video',
        'key': API_KEY
    }

    # Header stuff. Logic works, so I don't bother messing with it
    if event_type == 'live':
        params['eventType'] = 'live'
        params['order'] = order if order else 'viewCount'  # Default to viewCount if order is not specified
    elif order:
        params['order'] = order
    if max_results:
        params['maxResults'] = max_results
    if page_token:
        params['pageToken'] = page_token
    if cache_key == "viewCount":
        logger.debug_general(f"Making API call to fetch popular videos.")
    else:
        logger.debug_general(f"Making API call to fetch {event_type} videos.")

    async with aiohttp.ClientSession() as session:
        async with session.get(BASE_URL, params=params) as response:
            data = await response.text()
            json_data = json.loads(data)
            next_page_token = json_data.get('nextPageToken', -1)
            page_token = next_page_token
            urls = ["https://www.youtube.com/embed/" + item['id']['videoId'] for item in json_data['items']]

    # Update the cache and save it
    if cache_key == "viewCount":
        existing_urls = load_from_json().get('viewCount', {}).get('urls', [])
        urls = list(set(existing_urls + urls))
    data_to_save = {
        'last_updated': datetime.datetime.now().strftime('%Y-%m-%d'),
        'urls': urls,
        'last_page_token': page_token  # Save the last page token
    }
    cache_key = event_type or order
    save_to_json(data_to_save, key=cache_key)

    return urls, page_token


async def fetch_live_videos():
    # returns both the urls and the token in the chance we need it later
    urls, _ = await fetch_videos(event_type='live', max_results=LIVE_VIDEOS_LIMIT)
    return urls


async def fetch_top_100_videos():
    # returns both the urls and the token in the chance we need it later
    urls, _ = await fetch_videos(order='viewCount', max_results=POPULAR_VIDEOS_LIMIT)
    return urls
