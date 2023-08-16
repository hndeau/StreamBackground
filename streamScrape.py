from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as ec


def monitor_youtube_streams(channel_name, time_interval=10, wait_time=15, file_path='video_cache.json'):
    # Define the URL using the channel name
    url = f'https://www.youtube.com/@{channel_name}/streams'

    chrome_options = Options()
    chrome_options.add_argument("--headless")
    driver = webdriver.Chrome(options=chrome_options)
    try:
        # Navigate to the URL
        driver.get(url)

        # Wait for the element 'ytd-rich-grid-media' to be present
        WebDriverWait(driver, wait_time).until(
            ec.presence_of_element_located((By.CSS_SELECTOR, 'ytd-rich-grid-media'))
        )

        # Execute the JavaScript command and get the result
        result = driver.execute_script("return document.querySelectorAll('ytd-rich-grid-media').length")
    finally:
        driver.quit()
    return result - 1  # oceanexplorergov has a 'live' stream that's not actually live and this is fixing the inaccuracy
