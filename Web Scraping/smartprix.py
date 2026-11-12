import time

from selenium import webdriver
from selenium.webdriver.common.by import By

driver = webdriver.Chrome()

# open the url
driver.get('https://www.smartprix.com/mobiles')


# Keeps the script running as long as the browser window is open
try:
    while len(driver.window_handles) > 0:
        time.sleep(1)
except Exception:
    pass

