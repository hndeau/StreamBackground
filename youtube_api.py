import asyncio
import json
import logging
import os
import random
import sys
import time

import aiohttp

from cacher import CacheManager
from logger import logger
from utility_helpers import load_from_json, load_config

config, DEBUG_MODE = load_config()

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

API_KEY = os.environ.get('API_KEY') or config['API_KEY']  # <-- Modify this line
if not API_KEY:
    logging.error("API key not provided in config or environment variable.")
    sys.exit(1)

BASE_URL = config['BASE_URL']
CHANNEL_ID = config['CHANNEL_ID']
CHANNEL = config['CHANNEL']
BROWSER_WINDOW_SIZE = tuple(config['BROWSER_WINDOW_SIZE'])
LIVE_VIDEOS_LIMIT = config.get('LIVE_VIDEOS_LIMIT', 10)
VIDEO_CACHE = load_from_json() or {}
POPULAR_VIDEOS_LIMIT = config.get('POPULAR_VIDEOS_LIMIT', 100)
cache_manager = CacheManager(load_from_json())
random.seed(int(time.time()))


# -------- YOUTUBE API HANDLING -----------

async def fetch_videos(event_type=None, order=None, max_results=None, page_token=None, bypass_cache=False):
    logger.info(f"Fetching videos with event_type: {event_type}, order: {order}")
    cache_key = event_type or order

    # Check cache
    if not bypass_cache and cache_manager.is_cache_valid(cache_key):
        logger.info(
            f"Using cached {'popular' if cache_key == 'viewCount' else cache_key} videos. "
            f"Last updated on {cache_manager.load_from_cache(cache_key)['last_updated']}")
        return cache_manager.load_from_cache(cache_key)['urls'], page_token

    # Cache is invalid/inaccurate/bypassed
    params = {
        'part': 'id',
        'channelId': CHANNEL_ID,
        'type': 'video',
        'key': API_KEY
    }

    # Set eventType if event_type is 'live'
    if event_type == 'live':
        params['eventType'] = 'live'

    # Simplified order parameter assignment
    params['order'] = order or 'viewCount' if event_type == 'live' else order

    # Using dictionary comprehensions for conditional assignment
    params.update({key: value for key, value in [('maxResults', max_results), ('pageToken', page_token)] if value})

    # Logging statement
    logger_msg = f"Making API call to fetch {'popular' if cache_key == 'viewCount' else event_type} videos."
    logger.info(logger_msg)

    async with aiohttp.ClientSession() as session:
        async with session.get(BASE_URL, params=params) as response:
            data = await response.text()
            json_data = json.loads(data)
            next_page_token = json_data.get('nextPageToken', -1)
            page_token = next_page_token
            urls = ["https://www.youtube.com/embed/" + item['id']['videoId'] for item in json_data['items']]

    cache_manager.update_and_save_cache(urls, page_token, cache_key)

    return urls, page_token


async def fetch_live_videos():
    urls, _ = await fetch_videos(event_type='live', max_results=LIVE_VIDEOS_LIMIT)
    return urls


async def fetch_top_100_videos():
    urls, _ = await fetch_videos(order='viewCount', max_results=POPULAR_VIDEOS_LIMIT)
    return urls
