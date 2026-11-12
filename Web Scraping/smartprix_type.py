import os
import re
import sys
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import WebDriverException, TimeoutException

TYPES = {
    'Smartphone':    'https://www.smartprix.com/mobiles/smartphone-type',
    'Feature Phone': 'https://www.smartprix.com/mobiles/feature_phone-type',
    'Budget Phone':  'https://www.smartprix.com/mobiles/budget_phone-type',
    'Dual Sim':      'https://www.smartprix.com/mobiles/with-dual_sim',
    'Triple Sim':    'https://www.smartprix.com/mobiles/with-triple_sim',
}

MAX_FAILS_IN_A_ROW = 10
WAIT_FOR_NEW_ITEMS = 12
BAR_WIDTH = 30

PRODUCT_SELECTOR = 'div.sm-product'
HEADER_SELECTOR = 'div.pg-prf-head > div > div:first-child'   # "997 Mobile Phones"
BUTTON_XPATH = "//*[normalize-space(text())='Load More' or normalize-space(text())='Load more']"

CARDS_JS = """
return Array.from(document.querySelectorAll('div.sm-product')).map(c => {
    const a = c.querySelector('h2 a') || c.querySelector('a');
    return a ? [a.href, c.outerHTML] : null;
}).filter(Boolean);
"""


def read_total(driver, timeout=15):
    def read(d):
        try:
            text = d.find_element(By.CSS_SELECTOR, HEADER_SELECTOR).text
        except WebDriverException:
            return False
        m = re.search(r'([\d,]+)\s+Mobile', text)
        return int(m.group(1).replace(',', '')) if m else False
    try:
        return WebDriverWait(driver, timeout).until(read)
    except TimeoutException:
        return 0


def count_cards(driver):
    return len(driver.find_elements(By.CSS_SELECTOR, PRODUCT_SELECTOR))


def show(name, clicks, done, total):
    pct = min(done / total, 1) if total else 0
    filled = int(BAR_WIDTH * pct)
    bar = '#' * filled + '-' * (BAR_WIDTH - filled)
    line = f'{name:<13} | Click {clicks:>3} | [{bar}] {done}/{total} ({pct * 100:.0f}%)'
    sys.stdout.write('\r' + line.ljust(90))
    sys.stdout.flush()


def scrape_type(driver, name, url):
    driver.get(url)
    total = read_total(driver)
    cards = count_cards(driver)
    clicks = 0
    fails = 0
    show(name, clicks, cards, total)

    while (not total or cards < total) and fails < MAX_FAILS_IN_A_ROW:
        try:
            button = driver.find_element(By.XPATH, BUTTON_XPATH)
            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", button)
            time.sleep(0.4)
            driver.execute_script("arguments[0].click();", button)
            clicks += 1
        except WebDriverException:
            break  # no Load More button left

        start = time.time()
        new_cards = cards
        while time.time() - start < WAIT_FOR_NEW_ITEMS:
            time.sleep(0.4)
            new_cards = count_cards(driver)
            if new_cards > cards:
                break

        if new_cards > cards:
            fails = 0
            cards = new_cards
        else:
            fails += 1
        show(name, clicks, cards, total)

    # collect cards once at the end and remove duplicates by product link
    store = {}
    for href, html in driver.execute_script(CARDS_JS):
        store.setdefault(href, html)

    os.makedirs('htmls', exist_ok=True)
    fname = f"htmls/smartprix_{name.lower().replace(' ', '_')}.html"
    with open(fname, 'w', encoding='utf-8') as f:
        f.write('<html><body><div class="sm-products">\n')
        f.write('\n'.join(store.values()))
        f.write('\n</div></body></html>')

    sys.stdout.write('\n')
    return total, len(store), fname


options = webdriver.ChromeOptions()
options.add_argument('--log-level=3')
options.add_experimental_option('excludeSwitches', ['enable-logging'])
driver = webdriver.Chrome(options=options)

results = []
try:
    for name, url in TYPES.items():
        results.append((name, *scrape_type(driver, name, url)))
finally:
    driver.quit()

print('\n' + '=' * 74)
print(f'{"Type":<15}{"Listed":>9}{"Fetched":>10}{"Missing":>9}   File')
print('-' * 74)
for name, listed, fetched, fname in results:
    print(f'{name:<15}{listed:>9}{fetched:>10}{max(listed - fetched, 0):>9}   {fname}')
print('=' * 74)