import asyncio
import random
import threading
import keyboard
import time
import queue
from screeninfo import get_monitors
from selenium import webdriver
from selenium.webdriver import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait
from concurrent.futures import ThreadPoolExecutor


from utility_helpers import config
from youtube_api import cache_manager, fetch_live_videos, fetch_top_100_videos, BROWSER_WINDOW_SIZE, \
    fetch_videos, CHANNEL, POPULAR_VIDEOS_LIMIT, LIVE_VIDEOS_LIMIT
from yt_scrape import monitor_youtube_streams
from logger import logger


def create_driver(driver_name):
    logger.info(f"Creating driver for: {driver_name}")
    if driver_name == 'chrome':  # doesnt work
        options = ChromeOptions()
        options.add_argument('--kiosk')
        options.add_experimental_option("useAutomationExtension", False)
        options.add_experimental_option(
            'excludeSwitches',
            ['disable-sync',
             'disable-signin-promo',
             'disable-infobars'])
        browser = webdriver.Chrome(options=options)

    elif driver_name == 'firefox':
        options = FirefoxOptions()
        # Disable images
        options.set_preference('permissions.default.image', 2)
        # Disable CSS
        options.set_preference('permissions.default.stylesheet', 2)
        # Suppress pop-ups
        options.set_preference('dom.disable_open_during_load', True)
        options.set_preference("identity.fxaccounts.enabled", False)
        options.add_argument('--kiosk')
        browser = webdriver.Firefox(options=options)

    elif driver_name == 'edge':
        options = EdgeOptions()
        options.use_chromium = True
        options.add_argument('--kiosk')
        options.add_experimental_option("useAutomationExtension", False)
        options.add_experimental_option(
            'excludeSwitches',
            ['disable-sync',
             'disable-signin-promo',
             'enable-automation',
             'disable-infobars'])
        browser = webdriver.Edge(options=options)

    else:
        logger.error(f"Unsupported driver: {driver_name}")
        raise ValueError(f"Unsupported driver: {driver_name}")

    logger.info(f"Driver for {driver_name} created.")
    return browser


class Monitor:
    def __init__(self, browser, url=None):
        self.browser = browser
        self.current_url = url

    def play_video(self, url):
        if self.current_url == url:  # Prevent replaying the same video
            return
        try:
            logger.info(f'Video Started: {url}')
            self.browser.get(url)
            self.current_url = url
            player = WebDriverWait(self.browser, 4).until(  # can probably be lower
                ec.element_to_be_clickable((By.CSS_SELECTOR, "video.video-stream"))
            )
            player.send_keys('f', Keys.SPACE)
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
    def __init__(self, live_videos=None, top_videos=None):
        # Loading the tokens from the cache
        view_count_cache = cache_manager.load_from_cache('viewCount')
        live_video_cache = cache_manager.load_from_cache('live')

        self.next_popular_page_token = view_count_cache.get('last_page_token', None) if view_count_cache else None
        self.live_next_page_token = live_video_cache.get('last_page_token', None) if live_video_cache else None
        self.prev_count = len(live_video_cache.get('urls', []) if live_video_cache else [])
        self.driver_name = config.get('WEB_DRIVER', 'firefox').lower()
        self.monitors = []
        self.STOP_THREADS = False
        self.video_queue = queue.PriorityQueue()
        self.active_videos = set()  # Create a set of active videos

        # If live_videos is not provided, fetch it from the cache or API
        if live_videos is None:
            if cache_manager.is_cache_valid('live'):
                self.live_videos = live_video_cache.get('urls', [])
            else:
                self.live_videos = asyncio.run(fetch_live_videos())

        # If top_videos is not provided, fetch it from the cache or API
        if top_videos is None:
            if cache_manager.is_cache_valid('viewCount'):
                self.top_videos = view_count_cache.get('urls', [])
            else:
                self.top_videos = asyncio.run(fetch_top_100_videos())

        self.enqueue_videos(live_videos, top_videos)

    def is_stopped(self):
        return self.STOP_THREADS

    def stop(self):
        self.STOP_THREADS = True
        self.cleanup_browsers()
        self.active_videos.clear()

    def cleanup_browsers(self):
        """Close all browser windows."""
        for monitor in self.monitors:
            try:
                monitor.close()
            except Exception as e:
                logger.error(f"Failed to close browser: {e}")

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

    def enqueue_videos(self, live_videos, top_videos):
        logger.info(f"Enqueuing {len(live_videos)} live videos and {len(top_videos)} top videos.")
        random.shuffle(top_videos)
        for video, priority in zip(live_videos + top_videos, [0] * len(live_videos) + [1] * len(top_videos)):
            if video not in self.active_videos:
                self.video_queue.put((priority, video))

    def init_browser_and_return_monitor(self, monitor):
        """This method initializes the browser and returns the monitor instance."""
        browser = create_driver(self.driver_name)

        logger.info('Browser window opened')
        screen_width, screen_height = monitor.width, monitor.height
        window_width, window_height = BROWSER_WINDOW_SIZE
        position_x = (screen_width - window_width) // 2 + monitor.x
        position_y = (screen_height - window_height) // 2 + monitor.y

        browser.set_window_size(*BROWSER_WINDOW_SIZE)
        browser.set_window_position(position_x, position_y)

        monitor_instance = Monitor(browser)
        self.monitors.append(monitor_instance)
        logger.info(f'Browser initialized on monitor with position: x={position_x}, y={position_y}')
        return monitor_instance

    async def fetch_next_live_videos(self):
        # Check if the live video cache is valid
        if cache_manager.is_cache_valid('live'):
            self.live_videos = cache_manager.load_from_cache('live').get('urls', [])
        else:
            # Fetch from the API if cache is not valid
            self.live_videos, _ = await fetch_videos(event_type='live', max_results=LIVE_VIDEOS_LIMIT, page_token=None)

        for next_live_video in self.live_videos:
            self.video_queue.put((0, next_live_video))

        # Update this line to get the 'live' video count from the cache
        self.prev_count = len(cache_manager.load_from_cache('live').get('urls', []))

    async def fetch_and_enqueue_next_videos(self):
        while not self.is_stopped():
            # Check for new live videos
            result = await asyncio.get_running_loop().run_in_executor(None, monitor_youtube_streams, CHANNEL,
                                                                      self.driver_name)
            if result > self.prev_count:
                await self.fetch_next_live_videos()  # Fetch next set of live videos
                self.enqueue_videos(self.live_videos, [])  # Enqueue only the live videos
                self.prev_count = len(self.live_videos)  # Update the previous count

            # Check if the video queue is empty and fetch more popular videos
            if self.video_queue.empty() and self.next_popular_page_token and self.next_popular_page_token != -1:
                self.top_videos, self.next_popular_page_token = await fetch_videos(
                    order='viewCount',
                    max_results=POPULAR_VIDEOS_LIMIT,
                    page_token=self.next_popular_page_token,
                    bypass_cache=True)
                self.enqueue_videos([], self.top_videos)  # Enqueue only the top videos
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
        logger.info('Escape key hit')
        self.stop()
