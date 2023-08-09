import asyncio
import datetime
import json
import logging
import random
import sys
import threading
import time
import aiohttp
import keyboard

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

logger = logging.getLogger(__name__)
logging_level = logging.DEBUG if DEBUG_MODE else logging.WARNING
logging.basicConfig(level=logging_level)

VIDEO_CACHE = load_from_json() or {}
TOP_N = config.get('TOP_N', 100)  # default to 100 if not specified in config


# --------- MONITOR AND BROWSER HANDLING ---------
class Monitor:
    def __init__(self, browser, url=None):
        self.browser = browser
        self.current_url = url

    def is_playing_video(self):
        return self._video_has_ended()

    def play_video(self, url):
        try:
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
            WebDriverWait(self.browser, 15).until(
                EC.presence_of_element_located((By.ID, "movie_player"))
            )
            script = "return document.getElementById('movie_player').getCurrentTime()"
            initial_time = self.browser.execute_script(script)
            time.sleep(2)
            final_time = self.browser.execute_script(script)
            return not initial_time == final_time
        except Exception as e:
            logger.error(f"Error checking video status: {e}")
            return False


class MonitorManager:
    def __init__(self):
        self.monitors = []
        self.STOP_THREADS = False

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

    async def fetch_all_videos(self):
        return await asyncio.gather(fetch_live_videos(), fetch_top_100_videos())

    async def monitor_video_statuses(self, monitor):
        while not self.is_stopped():
            live_videos, top_videos = await self.fetch_all_videos()
            if monitor.is_page_loaded() and not monitor.is_playing_video():
                for live_video in live_videos:
                    if live_video not in [m.current_url for m in self.monitors]:
                        monitor.play_video(live_video)
                        break
                else:
                    selected_video = random.choice(top_videos)
                    while selected_video in [m.current_url for m in self.monitors]:
                        selected_video = random.choice(top_videos)
                    monitor.play_video(selected_video)
            await asyncio.sleep(5)

    def init_browser_and_return_monitor(self, monitor):
        """This method initializes the browser and returns the monitor instance."""
        browser = webdriver.Firefox()
        screen_width, screen_height = monitor.width, monitor.height
        window_width, window_height = BROWSER_WINDOW_SIZE
        position_x = (screen_width - window_width) // 2 + monitor.x
        position_y = (screen_height - window_height) // 2 + monitor.y

        browser.set_window_size(*BROWSER_WINDOW_SIZE)
        browser.set_window_position(position_x, position_y)

        monitor_instance = Monitor(browser)
        self.monitors.append(monitor_instance)
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
async def fetch_videos(event_type=None, order=None, max_results=None):
    key = 'live' if event_type == 'live' else 'popular'

    if key in VIDEO_CACHE and 'last_updated' in VIDEO_CACHE[key]:
        last_updated = datetime.datetime.strptime(VIDEO_CACHE[key]['last_updated'], '%Y-%m-%d')
        # Adjust the caching time
        caching_time = 1 if key == 'live' else 60
        if (datetime.datetime.now() - last_updated).days < caching_time:
            logger.debug(f"Using cached {key} videos. Last updated on {VIDEO_CACHE[key]['last_updated']}")
            return VIDEO_CACHE[key]['urls']

    params = {
        'part': 'id',
        'channelId': CHANNEL_ID,
        'type': 'video',
        'key': API_KEY
    }

    if event_type:
        params['eventType'] = event_type
    if order:
        params['order'] = order
    if max_results:
        params['maxResults'] = max_results

    async with aiohttp.ClientSession() as session:
        async with session.get(BASE_URL, params=params) as response:
            data = await response.text()
            json_data = json.loads(data)
            urls = ["https://www.youtube.com/embed/" + item['id']['videoId'] for item in json_data['items']]

    # Update the cache and save it
    data_to_save = {
        'last_updated': datetime.datetime.now().strftime('%Y-%m-%d'),
        'urls': urls
    }
    save_to_json(data_to_save, key=key)
    return urls


async def fetch_live_videos():
    return await fetch_videos(event_type='live')


async def fetch_top_100_videos():
    return await fetch_videos(order='viewCount', max_results=TOP_N)


# ---------- MAIN EXECUTION FUNCTIONS ------------


if __name__ == "__main__":
    manager = MonitorManager()

    # Start the key listener thread first
    key_thread = threading.Thread(target=manager.key_listener)
    key_thread.start()

    try:
        asyncio.run(manager.monitor_all_screens())
    finally:
        key_thread.join()
