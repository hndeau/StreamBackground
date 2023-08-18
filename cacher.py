import datetime

import logging

from utility_helpers import save_to_json


class CacheManager:

    def __init__(self, initial_cache=None):

        self.VIDEO_CACHE = initial_cache or {}

        self.logger = logging.getLogger(__name__)

    def load_from_cache(self, key):

        return self.VIDEO_CACHE.get(key)

    def save_to_cache(self, data, key):

        self.VIDEO_CACHE[key] = data

        save_to_json(data, key=key)

        self.logger.debug_general(f"Saved data to cache for key: {key}")

    def is_cache_valid(self, cache_key, caching_time=None):

        if cache_key in self.VIDEO_CACHE and 'last_updated' in self.VIDEO_CACHE[cache_key]:

            last_updated = datetime.datetime.strptime(self.VIDEO_CACHE[cache_key]['last_updated'], '%Y-%m-%d')

            caching_time = caching_time or (1 if cache_key == 'live' else 60)

            if (datetime.datetime.now() - last_updated).days < caching_time:
                return True

        return False

    def update_and_save_cache(self, urls, page_token, cache_key):

        if cache_key == "viewCount":
            existing_urls = self.load_from_cache('viewCount').get('urls', [])

            urls = list(set(existing_urls + urls))

        data_to_save = {

            'last_updated': datetime.datetime.now().strftime('%Y-%m-%d'),

            'urls': urls,

            'last_page_token': page_token  # Save the last page token

        }

        self.save_to_cache(data_to_save, key=cache_key)