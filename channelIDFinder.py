# import re
# import json
# from googleapiclient.discovery import build
#
#
# # Function to read API key from the config file
# def read_api_key_from_config(file_path='config.json'):
#     with open(file_path, 'r') as file:
#         config = json.load(file)
#         return config.get('API_KEY')
#     return None
#
# # Function to get channel ID from a YouTube username
# def get_channel_id_from_username(username, api_key=read_api_key_from_config()):
#     youtube = build('youtube', 'v3', developerKey=api_key)
#     request = youtube.channels().list(
#         part='id',
#         forUsername=username
#     )
#     response = request.execute()
#     if response['items']:
#         return response['items'][0]['id']
#     return None
#
# # Function to get channel ID from a YouTube URL
# def get_channel_id(url, api_key=read_api_key_from_config()):
#     # Check if the URL has the channel ID format
#     match_channel_id = re.search(r'youtube\.com/channel/([a-zA-Z0-9_-]+)', url)
#     if match_channel_id:
#         return match_channel_id.group(1)
#
#     # Check if the URL has the username format
#     match_username = re.search(r'youtube\.com/user/([a-zA-Z0-9_-]+)', url)
#     if match_username:
#         username = match_username.group(1)
#         return get_channel_id_from_username(username, api_key)
#
#     print("Invalid YouTube channel URL")
#     return None
#
#
# # if __name__ == "__main__":
# #     # Test URLs
# #     url1 = "https://www.youtube.com/channel/UC_x5XG1OV2P6uZZ5FSM9Ttw"
# #     url2 = "https://www.youtube.com/user/Google"
# #
# #     print("Channel ID for URL 1:", get_channel_id(url1))
# #     print("Channel ID for URL 2:", get_channel_id(url2))
