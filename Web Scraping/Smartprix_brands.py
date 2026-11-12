import os
import re
import sys
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import WebDriverException, TimeoutException

BASE = 'https://www.smartprix.com'
ALL_URL = f'{BASE}/mobiles'

# Brand name -> URL slug. Pattern confirmed for Samsung (/mobiles/samsung-brand).
# For any other brand, click it on the site and copy the slug from the address bar.
# Add more brands from the sidebar to cover the full 19,871.
BRANDS = {
    'Samsung':  'samsung-brand',
    'Vivo':     'vivo-brand',
    'Realme':   'realme-brand',
    'Motorola': 'motorola-brand',
    'OPPO':     'oppo-brand',
    'OnePlus':  'oneplus-brand',
    'Xiaomi':   'xiaomi-brand',
    'Poco':     'poco-brand',
    'Apple':    'apple-brand',
}

PRODUCT_SELECTOR = 'div.sm-product'
HEADER_SELECTOR = 'div.pg-prf-head > div > div:first-child'   # e.g. "997 Mobile Phones"
BUTTON_XPATH = "//*[normalize-space(text())='Load More' or normalize-space(text())='Load more']"

MAX_FAILS_IN_A_ROW = 3
WAIT_FOR_NEW_ITEMS = 10
BAR_WIDTH = 30


def count_products(driver):
    return len(driver.find_elements(By.CSS_SELECTOR, PRODUCT_SELECTOR))


def listed_total(driver):
    """Read the '997 Mobile Phones' number shown at the top of the listing."""
    def read(d):
        try:
            text = d.find_element(By.CSS_SELECTOR, HEADER_SELECTOR).text
        except WebDriverException:
            return False
        m = re.search(r'([\d,]+)\s+Mobile', text)
        return int(m.group(1).replace(',', '')) if m else False

    try:
        return WebDriverWait(driver, 20).until(read)
    except TimeoutException:
        return 0


def show(brand, clicks, fetched, total):
    pct = min(fetched / total, 1) if total else 0
    filled = int(BAR_WIDTH * pct)
    bar = '#' * filled + '-' * (BAR_WIDTH - filled)
    line = f'{brand:<9} | Click {clicks:>3} | [{bar}] {fetched}/{total} ({pct * 100:.0f}%)'
    sys.stdout.write('\r' + line.ljust(95))
    sys.stdout.flush()


def scrape_brand(driver, brand, slug):
    driver.get(f'{ALL_URL}/{slug}')
    total = listed_total(driver)
    time.sleep(1)
    fetched = count_products(driver)
    clicks = 0
    fails = 0
    show(brand, clicks, fetched, total)

    while (not total or fetched < total) and fails < MAX_FAILS_IN_A_ROW:
        try:
            button = driver.find_element(By.XPATH, BUTTON_XPATH)
            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", button
            )
            time.sleep(0.4)
            driver.execute_script("arguments[0].click();", button)
            clicks += 1
        except WebDriverException:
            break  # no button left

        start = time.time()
        new_count = fetched
        while time.time() - start < WAIT_FOR_NEW_ITEMS:
            time.sleep(0.4)
            new_count = count_products(driver)
            if new_count > fetched:
                break

        if new_count > fetched:
            fails = 0
            fetched = new_count
        else:
            fails += 1
        show(brand, clicks, fetched, total)

    os.makedirs('htmls', exist_ok=True)
    with open(f'htmls/smartprix_{brand.lower()}.html', 'w', encoding='utf-8') as f:
        f.write(driver.page_source)

    sys.stdout.write('\n')
    return total, fetched


options = webdriver.ChromeOptions()
options.add_argument('--log-level=3')
options.add_experimental_option('excludeSwitches', ['enable-logging'])
driver = webdriver.Chrome(options=options)

results = {}
try:
    driver.get(ALL_URL)
    site_total = listed_total(driver)

    for brand, slug in BRANDS.items():
        results[brand] = scrape_brand(driver, brand, slug)
finally:
    driver.quit()

# ---------- summary ----------
print('\n' + '=' * 48)
print(f'{"Brand":<10}{"Listed":>10}{"Fetched":>10}{"Missing":>10}')
print('-' * 48)
sum_listed = sum_fetched = 0
for brand, (listed, fetched) in results.items():
    sum_listed += listed
    sum_fetched += fetched
    print(f'{brand:<10}{listed:>10}{fetched:>10}{max(listed - fetched, 0):>10}')
print('-' * 48)
print(f'{"TOTAL":<10}{sum_listed:>10}{sum_fetched:>10}{max(sum_listed - sum_fetched, 0):>10}')
print('=' * 48)
print(f'Listed on website (all phones): {site_total}')
print(f'Listed for brands scraped     : {sum_listed}')
print(f'Fetched                       : {sum_fetched}')
print(f'Brands not covered yet        : {max(site_total - sum_listed, 0)}')