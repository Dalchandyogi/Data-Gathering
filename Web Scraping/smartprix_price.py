import os
import re
import sys
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import WebDriverException, TimeoutException

BASE = 'https://www.smartprix.com/mobiles'

# Official price bands from the site. (None, 5000) = "below 5000", (30000, None) = "above 30000".
START_BANDS = [(None, 5000), (5000, 10000), (10000, 15000),
               (15000, 20000), (20000, 30000), (30000, None)]

LIMIT = 900                 # a listing larger than this gets split into smaller price ranges
MAX_FAILS_IN_A_ROW = 5
WAIT_FOR_NEW_ITEMS = 12
BAR_WIDTH = 30

PRODUCT_SELECTOR = 'div.sm-product'
HEADER_SELECTOR = 'div.pg-prf-head > div > div:first-child'   # "997 Mobile Phones"
BUTTON_XPATH = "//*[normalize-space(text())='Load More' or normalize-space(text())='Load more']"

LINKS_JS = """
return Array.from(document.querySelectorAll('div.sm-product')).map(c => {
    const a = c.querySelector('h2 a') || c.querySelector('a');
    return a ? a.href : null;
}).filter(Boolean);
"""


# ---------- helpers ----------
def price_slug(lo, hi):
    if lo is None:
        return f'price-below_{hi}'
    if hi is None:
        return f'price-above_{lo}'
    return f'price-{lo}_to_{hi}'


def label(lo, hi):
    if lo is None:
        return f'below {hi}'
    if hi is None:
        return f'above {lo}'
    return f'{lo}-{hi}'


def can_split(lo, hi):
    if lo is None:
        return hi >= 4
    if hi is None:
        return lo < 5_000_000
    return hi - lo >= 2


def split(lo, hi):
    if lo is None:
        mid = hi // 2
        return [(None, mid), (mid, hi)]
    if hi is None:
        mid = lo * 2
        return [(lo, mid), (mid, None)]
    mid = (lo + hi) // 2
    return [(lo, mid), (mid, hi)]


def read_total(driver, timeout=12):
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
        return None


def count_cards(driver):
    return len(driver.find_elements(By.CSS_SELECTOR, PRODUCT_SELECTOR))


def get_links(driver):
    return set(driver.execute_script(LINKS_JS))


def show(rng, clicks, done, site_total, note=''):
    pct = min(done / site_total, 1) if site_total else 0
    filled = int(BAR_WIDTH * pct)
    bar = '#' * filled + '-' * (BAR_WIDTH - filled)
    line = f'{rng:<13} | Click {clicks:>3} | [{bar}] {done}/{site_total} ({pct * 100:.0f}%) {note}'
    sys.stdout.write('\r' + line.ljust(100))
    sys.stdout.flush()


def load_range(driver, lo, hi):
    """Open one price range and return its listed total (0 if empty / unreadable)."""
    url = f'{BASE}/{price_slug(lo, hi)}'
    driver.get(url)
    total = read_total(driver)
    if total is None:               # one retry if the page didn't render
        driver.get(url)
        total = read_total(driver)
    return total or 0


def click_until_loaded(driver, total, rng, seen, site_total):
    """Click Load More until `total` cards are loaded. Returns (cards, links)."""
    cards = count_cards(driver)
    links = get_links(driver)
    clicks = 0
    fails = 0
    show(rng, clicks, len(seen | links), site_total)

    while cards < total and fails < MAX_FAILS_IN_A_ROW:
        try:
            button = driver.find_element(By.XPATH, BUTTON_XPATH)
            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", button)
            time.sleep(0.4)
            driver.execute_script("arguments[0].click();", button)
            clicks += 1
        except WebDriverException:
            break

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
            links = get_links(driver)
        else:
            fails += 1
        show(rng, clicks, len(seen | links), site_total)

    return cards, links


# ---------- main ----------
options = webdriver.ChromeOptions()
options.add_argument('--log-level=3')
options.add_experimental_option('excludeSwitches', ['enable-logging'])
driver = webdriver.Chrome(options=options)
os.makedirs('htmls', exist_ok=True)

seen = set()          # unique product links collected so far
leaves = []           # (range, listed, cards, status)
site_total = 0

try:
    driver.get(BASE)
    site_total = read_total(driver) or 0

    queue = list(START_BANDS)
    while queue:
        lo, hi = queue.pop(0)
        rng = label(lo, hi)
        show(rng, 0, len(seen), site_total, 'checking...')

        total = load_range(driver, lo, hi)
        if total == 0:
            continue

        if total > LIMIT and can_split(lo, hi):
            queue = split(lo, hi) + queue
            continue

        # up to 2 attempts (reload between) to load the whole range
        best_cards, best_links = 0, set()
        for attempt in range(2):
            if attempt:
                load_range(driver, lo, hi)
            cards, links = click_until_loaded(driver, total, rng, seen, site_total)
            seen |= links
            if cards > best_cards:
                best_cards, best_links = cards, links
            if cards >= total:
                break

        if best_cards < total and can_split(lo, hi):
            # still incomplete -> try smaller ranges instead
            queue = split(lo, hi) + queue
            continue

        status = 'ok' if best_cards >= total else 'INCOMPLETE'
        leaves.append((rng, total, best_cards, status))
        fname = f'htmls/smartprix_price_{price_slug(lo, hi)}.html'
        with open(fname, 'w', encoding='utf-8') as f:
            f.write(driver.page_source)
        sys.stdout.write('\n')
finally:
    driver.quit()
    with open('htmls/smartprix_links.txt', 'w', encoding='utf-8') as f:
        f.write('\n'.join(sorted(seen)))

# ---------- summary ----------
print('\n' + '=' * 52)
print(f'{"Price range":<14}{"Listed":>9}{"Cards":>9}  Status')
print('-' * 52)
for rng, total, cards, status in leaves:
    print(f'{rng:<14}{total:>9}{cards:>9}  {status}')
print('=' * 52)
print(f'Listed on website : {site_total}')
print(f'Unique phones got : {len(seen)}')
print(f'Missing           : {max(site_total - len(seen), 0)}')