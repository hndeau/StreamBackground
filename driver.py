import threading
import asyncio

from browser_monitor import MonitorManager, fetch_top_100_videos, fetch_live_videos


async def fetch_videos_and_initialize_manager():
    live_videos, top_videos = await asyncio.gather(
        fetch_live_videos(),
        fetch_top_100_videos()
    )
    return MonitorManager(live_videos, top_videos)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    manager = loop.run_until_complete(fetch_videos_and_initialize_manager())

    # Start the key listener thread first
    key_thread = threading.Thread(target=manager.key_listener)
    key_thread.start()

    try:
        loop.run_until_complete(manager.monitor_all_screens())
    finally:
        key_thread.join()
