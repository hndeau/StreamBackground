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

from utility_helpers import load_from_json, save_to_json

# --------- CONFIG AND INITIALIZATION -----------

# Load the config file
with open("config.json", "r") as file:
    config = json.load(file)

DEBUG_MODE = "--debug" in sys.argv or "-d" in sys.argv
API_KEY = config['API_KEY']

if not API_KEY:
    logging.error("API key not provided in config.")
    sys.exit(1)

# Constants from Config
BASE_URL = config['BASE_URL']
CHANNEL_ID = config['CHANNEL_ID']
BROWSER_WINDOW_SIZE = tuple(config['BROWSER_WINDOW_SIZE'])

# Setup Logging
logger = logging.getLogger(__name__)
logging_level = logging.DEBUG if DEBUG_MODE else logging.WARNING
logging.basicConfig(level=logging_level)

# Global Variables
monitors = []
random.seed(time.time())
threads = []
STOP_THREADS = False
VIDEO_CACHE = load_from_json() or {}
TOP_N = config.get('TOP_N', 100)  # default to 100 if not specified in config


# --------- MONITOR AND BROWSER HANDLING ---------
class Monitor:
    def __init__(self, browser, url=None):
        self.browser = browser
        self.current_url = url

    def is_playing_video(self):
        if STOP_THREADS:
            return False
        return self._video_has_ended()

    def play_video(self, url):
        if STOP_THREADS:
            return
        self.browser.get(url)
        self.current_url = url
        player = WebDriverWait(self.browser, 15).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "video.video-stream"))
        )
        player.send_keys('F')
        player.send_keys(Keys.SPACE)

    def close(self):
        self.browser.quit()

    def is_page_loaded(self):
        if STOP_THREADS:
            return False
        """Check if the page is completely loaded."""
        try:
            return self.browser.execute_script("return document.readyState") == "complete"
        except Exception as e:
            logger.error(f"Error checking page load status: {e}")
            return False

    def _video_has_ended(self):
        if STOP_THREADS:
            return False
        try:
            # Wait for the element to be present
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


def cleanup_browsers():
    """Close all browser windows."""
    for monitor in monitors:
        monitor.close()


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
async def monitor_video_statuses(monitor):
    while True:
        if STOP_THREADS:
            return
        live_videos = await fetch_live_videos()
        top_videos = await fetch_top_100_videos()
        if monitor.is_page_loaded() and not monitor.is_playing_video():
            for live_video in live_videos:
                if live_video not in [m.current_url for m in monitors]:
                    monitor.play_video(live_video)
                    break
            else:
                selected_video = random.choice(top_videos)
                while selected_video in [m.current_url for m in monitors]:
                    selected_video = random.choice(top_videos)
                monitor.play_video(selected_video)
        await asyncio.sleep(5)


def key_listener():
    """Listens for a key press to stop all threads."""
    global STOP_THREADS
    keyboard.wait('esc')
    logger.debug('Escape key pressed.')  # waits until the 'esc' key is pressed
    STOP_THREADS = True
    logger.debug('STOP_THREADS set to True.')
    cleanup_browsers()
    loop.stop()


def handle_monitor(monitor):
    """Function to handle each monitor in its own thread."""
    global STOP_THREADS
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    browser = webdriver.Firefox()

    # Get the screen resolution for the current monitor
    screen_width, screen_height = monitor.width, monitor.height
    window_width, window_height = BROWSER_WINDOW_SIZE

    # Calculate top-left position to center the window on the screen
    position_x = (screen_width - window_width) // 2 + monitor.x
    position_y = (screen_height - window_height) // 2 + monitor.y

    browser.set_window_size(*BROWSER_WINDOW_SIZE)
    browser.set_window_position(position_x, position_y)

    monitor_instance = Monitor(browser)
    monitors.append(monitor_instance)

    while not STOP_THREADS:
        logger.debug('handle_monitor loop running.')
        loop.run_until_complete(monitor_video_statuses(monitor_instance))
    loop.close()


def open_browsers_for_monitors():
    global threads
    detected_monitors = get_monitors()
    logger.debug(f"Detected screens: {[monitor for monitor in detected_monitors]}")

    for monitor in detected_monitors:
        thread = threading.Thread(target=handle_monitor, args=(monitor,))
        thread.start()
        threads.append(thread)


async def main_execution():
    open_browsers_for_monitors()


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main_execution())
    finally:
        # Start the key listener thread
        key_thread = threading.Thread(target=key_listener)
        key_thread.start()
        # Ensure all threads are joined and closed properly
        for thread in threads:
            thread.join()
        key_thread.join()
