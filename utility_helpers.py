import json
import logging
import os

# --------- CONFIG AND INITIALIZATION -----------
# Load the config file
with open("config.json", "r") as f:
    config = json.load(f)

JSON_FILE = config['JSON_FILE']
logger = logging.getLogger(__name__)


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
    if os.path.exists(filename):
        with open(filename, 'r') as file:
            return json.load(file)
    return None
