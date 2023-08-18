from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as ec


def monitor_youtube_streams(channel_name, driver_name='chrome', wait_time=10):
    # Define the URL using the channel name
    url = f'https://www.youtube.com/@{channel_name}/streams'

    if driver_name == 'chrome':
        options = ChromeOptions()
        options.add_argument("--headless")
        driver = webdriver.Chrome(options=options)
    elif driver_name == 'firefox':
        options = FirefoxOptions()
        options.add_argument("--headless")
        driver = webdriver.Firefox(options=options)
    elif driver_name == 'edge':
        options = EdgeOptions()
        options.use_chromium = True
        options.add_argument("--headless")
        driver = webdriver.Edge(options=options)
    else:
        raise ValueError(f"Unsupported driver: {driver_name}")

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
