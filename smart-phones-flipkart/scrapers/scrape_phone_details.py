import time

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from selenium.common.exceptions import (
    StaleElementReferenceException,
    ElementClickInterceptedException,
    ElementNotInteractableException,
)


# ---------------------------------------------------------------------------
# Click helpers
# ---------------------------------------------------------------------------

def find_visible(driver, xpath):
    """Return the first displayed element matching xpath, else None."""
    for el in driver.find_elements(By.XPATH, xpath):
        try:
            if el.is_displayed():
                return el
        except StaleElementReferenceException:
            continue
    return None


def scroll_until_found(driver, xpath, max_scrolls=15, step=700):
    """Scroll down in steps until a visible element matching xpath appears."""
    for _ in range(max_scrolls):
        el = find_visible(driver, xpath)
        if el:
            return el
        driver.execute_script("window.scrollBy(0, arguments[0]);", step)
        time.sleep(0.8)
    return find_visible(driver, xpath)


def safe_click(driver, element):
    """Scroll element into view, try a normal click, fall back to JS click."""
    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center'});", element
    )
    time.sleep(1)

    try:
        element.click()
    except (ElementClickInterceptedException, ElementNotInteractableException):
        # Something is overlapping the element -> click via JavaScript
        driver.execute_script("arguments[0].click();", element)


def click_by_exact_text(driver, text, attempts=3):
    # text() = the element's OWN text, so only the innermost element matches
    xpath = f"//*[normalize-space(text())='{text}']"

    for attempt in range(attempts):
        try:
            element = scroll_until_found(driver, xpath)

            if element is None:
                print(f"'{text}' not found (attempt {attempt + 1}).")
                continue

            safe_click(driver, element)
            print(f"'{text}' clicked.")
            time.sleep(2)
            return True

        except StaleElementReferenceException:
            print(f"Retrying '{text}' click: {attempt + 1}")

    print(f"Unable to click '{text}'.")
    return False


# ---------------------------------------------------------------------------
# Specification extraction
# ---------------------------------------------------------------------------

# Runs inside the browser and returns [[section, label, value], ...].
#
# Page structure (from the saved product page):
#   div.grid-formation                      -> one section (e.g. "Camera Features")
#     div[font="default-fk-font-l"]         -> section title
#     div.grid-formation-dynamic            -> one specification cell
#       div[font="default-fk-font-m"]       -> label  (e.g. "Digital Zoom")
#       div[font="s"]                       -> value  (e.g. "Yes")
#
# textContent is used (not innerText) because the specs sit inside a
# container that can be hidden/collapsed; innerText returns "" for those.
EXTRACT_SPECS_JS = """
const rows = [];

document.querySelectorAll('div.grid-formation-dynamic').forEach(cell => {
    const label = cell.querySelector('div[font="default-fk-font-m"]');
    if (!label) return;

    const value = label.nextElementSibling;

    const group = cell.closest('div.grid-formation');
    const title = group
        ? group.querySelector('div[font="default-fk-font-l"]')
        : null;

    rows.push([
        title ? title.textContent.trim() : '',
        label.textContent.trim(),
        value ? value.textContent.trim() : ''
    ]);
});

return rows;
"""


def extract_all_specs(driver):
    """
    Return every specification on the page.

    Result: list of dicts -> [{"section": ..., "label": ..., "value": ...}, ...]
    """
    rows = driver.execute_script(EXTRACT_SPECS_JS) or []

    return [
        {"section": section, "label": label, "value": value}
        for section, label, value in rows
        if label  # skip empty cells
    ]


def specs_to_flat_dict(specs):
    """
    Turn the list from extract_all_specs() into one flat dict
    {label: value}, ready to become a single CSV row.
    If the same label appears in two sections, the section name is
    added in front so nothing gets overwritten.
    """
    flat = {}

    for spec in specs:
        key = spec["label"]

        if key in flat:
            key = f"{spec['section']} - {spec['label']}"

        flat[key] = spec["value"]

    return flat


# ---------------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------------

def scrape_phone_details(driver, product_url):

    wait = WebDriverWait(driver, 20)

    # 1. Open product page
    driver.get(product_url)
    wait.until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )
    time.sleep(2)
    print("Product page opened.")

    # 2. Scroll down + click Specifications
    if not click_by_exact_text(driver, "Specifications"):
        return None

    # 3. Click "See more" (exact text avoids Showcase's "Show More")
    if not click_by_exact_text(driver, "See more"):
        print("Specifications 'See more' button not found, continuing anyway.")

    time.sleep(2)

    # 4. Extract every specification (all sections, all labels)
    specs = extract_all_specs(driver)

    if not specs:
        print("No specifications found.")
        return None

    print(f"Specifications found: {len(specs)}")

    # 5. Print grouped by section
    current_section = None
    for spec in specs:
        if spec["section"] != current_section:
            current_section = spec["section"]
            print(f"\n[{current_section}]")
        print(f"  {spec['label']}: {spec['value']}")
    print()

    # 6. Return a flat dict -> easy to write as one CSV row later
    return specs_to_flat_dict(specs)