
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from helpers import Helpers
from scrapers.scrape_phone_list import scrape_phone_list


url = "https://www.flipkart.com/search?q=smartphones"

options = Options()
options.add_argument("--start-maximized")
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_argument("--disable-blink-features=AutomationControlled")

driver = webdriver.Chrome(options=options)
helpers = Helpers(driver)

try:

    driver.get(url)
    time.sleep(3)

    # Select brand
    helpers.open_brand_popup()
    helpers.select_brand(2)

    # Apply filters
    helpers.apply_filters()

    filtered_url = driver.current_url
    print("Filtered URL:", filtered_url)

    # Scrape all listing pages
    all_products = scrape_phone_list(helpers)

    input("Press Enter to close browser...")

finally:
    driver.quit()
