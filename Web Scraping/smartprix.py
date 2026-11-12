import os
import sys
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException

URL = 'https://www.smartprix.com/mobiles'
SAVE_PATH = 'htmls/smartprix_phones.html'

PRODUCT_SELECTOR = 'div.sm-product'
BUTTON_XPATH = "//*[normalize-space(text())='Load More' or normalize-space(text())='Load more']"

MAX_FAILS_IN_A_ROW = 8      # stop only after this many consecutive failed attempts
WAIT_FOR_NEW_ITEMS = 15     # seconds to wait for new products after each click
TARGET_PHONES = 19871
BAR_WIDTH = 40


def count_products(driver):
    return len(driver.find_elements(By.CSS_SELECTOR, PRODUCT_SELECTOR))


def save_html(driver, path=SAVE_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(driver.page_source)


def show(clicks, count):
    pct = min(count / TARGET_PHONES, 1)
    filled = int(BAR_WIDTH * pct)
    bar = '#' * filled + '-' * (BAR_WIDTH - filled)
    sys.stdout.write(f'\rClick {clicks:>4} | [{bar}] {count}/{TARGET_PHONES} ({pct * 100:.0f}%)   ')
    sys.stdout.flush()


options = webdriver.ChromeOptions()
options.add_argument('--log-level=3')
options.add_experimental_option('excludeSwitches', ['enable-logging'])
driver = webdriver.Chrome(options=options)
driver.get(URL)
time.sleep(3)

fails = 0
clicks = 0
last_count = count_products(driver)
show(clicks, last_count)

try:
    while last_count < TARGET_PHONES and fails < MAX_FAILS_IN_A_ROW:
        try:
            button = driver.find_element(By.XPATH, BUTTON_XPATH)
            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", button
            )
            time.sleep(0.5)
            # JS click avoids "click intercepted" by ads / sticky headers
            driver.execute_script("arguments[0].click();", button)
            clicks += 1
        except WebDriverException:
            # button missing for a moment (page is re-rendering) -> retry, don't quit
            fails += 1
            driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
            time.sleep(2)
            continue

        # wait until the product count actually increases
        start = time.time()
        new_count = last_count
        while time.time() - start < WAIT_FOR_NEW_ITEMS:
            time.sleep(0.5)
            new_count = count_products(driver)
            if new_count > last_count:
                break

        if new_count > last_count:
            fails = 0
            last_count = new_count
        else:
            fails += 1

        show(clicks, last_count)

        # save progress every 50 clicks so nothing is lost on a crash
        if clicks % 50 == 0:
            save_html(driver)

    save_html(driver)
    print(f'\nListed on website: {TARGET_PHONES} | Fetched: {last_count} | '
          f'Missing: {max(TARGET_PHONES - last_count, 0)}')
    print(f'Saved to {SAVE_PATH}')
finally:
    driver.quit()