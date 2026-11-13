
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from helpers import Helpers
from scrapers.scrape_phone_list import scrape_phone_list
from  scrapers.scrape_phone_details import scrape_phone_details


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

    product_url = all_products[0]["url"]
    p_u = 'https://www.flipkart.com/motorola-edge-70-fusion-pantone-silhouette-512-gb/p/itm296e356d06dfe?pid=MOBHNSA6EXSZXYUH&lid=LSTMOBHNSA6EXSZXYUHIGVMTN&marketplace=FLIPKART&q=smartphones&store=tyy%2F4io&srno=s_1_10&otracker=search&fm=organic&iid=f61bf7ad-f1a9-4fc6-b460-041d850bb240.MOBHNSA6EXSZXYUH.SEARCH&ppt=sp&ppn=sp&qH=6ea4465d0add4685&ov_redirect=true'
    scrape_phone_details(driver, product_url)

    input("Press Enter to close browser...")

finally:
    driver.quit()
