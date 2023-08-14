import json
import logging
import os

# Default config initialization
DEFAULT_CONFIG = {
    "API_KEY": "",
    "BASE_URL": "https://www.googleapis.com/youtube/v3/search",
    "CHANNEL_ID": "",
    "BROWSER_WINDOW_SIZE": [1024, 768],
    "JSON_FILE": "video_cache.json",
    "TOP_N": 100
}

CONFIG_FILE = "config.json"

# Check if the config file exists, if not create it with default values
if not os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, "w") as file:
        json.dump(DEFAULT_CONFIG, file)
    logging.warning(f"{CONFIG_FILE} not found. A new file has been created with default values.")

# Load the config file
with open(CONFIG_FILE, "r") as f:
    config = json.load(f)

JSON_FILE = config['JSON_FILE']
logger = logging.getLogger(__name__)

# Check if the JSON file exists, if not create it with an empty object
if not os.path.exists(JSON_FILE):
    with open(JSON_FILE, "w") as file:
        json.dump({}, file)
    logger.debug(f"{JSON_FILE} not found. A new file has been created.")


# ----------- UTILITY FUNCTIONS -------------
def save_to_json(data, key=None, filename=JSON_FILE):
    """Save data to a JSON file under a specific key or replace the entire content if no key is provided."""
    existing_data = load_from_json(filename) or {}

    if key:
        existing_data[key] = data
    else:
        existing_data = data

    with open(filename, 'w') as file:
        json.dump(existing_data, file)
    logger.debug(f"Saved data to {filename}")


def load_from_json(filename=JSON_FILE):
    """Load data from a JSON file."""
    try:
        with open(filename, 'r') as file:
            return json.load(file)
    except json.JSONDecodeError:
        # Return an empty dictionary if there's a JSON decode error
        return {}
