import time
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException
from urllib.parse import urljoin


class Helpers:

    def __init__(self, driver, timeout: int = 20):
        # The driver is created in main.py and passed in, so there is only ONE browser.
        self.driver = driver
        self.wait = WebDriverWait(driver, timeout)

        self.ALL_BRANDS_BTN = (
            '//*[@id="container"]/div/div[3]/div[1]/div[1]/div/'
            'div[1]/div/section[2]/div[2]/div[2]/span'
        )
        self.SEARCH_BRAND_INPUT = '//input[@placeholder="Search Brand"]'
        self.APPLY_FILTERS_BTN = '//span[normalize-space()="Apply Filters"]'
        # Every brand row inside the popup, in on-screen order
        self.BRAND_ROWS = '//div[contains(@class,"OjMtYi")]//div[@title and contains(@class,"tx4xZf")]'

    # ---------- popup ----------
    def open_brand_popup(self) -> None:
        self.wait.until(EC.element_to_be_clickable((By.XPATH, self.ALL_BRANDS_BTN))).click()
        self.wait.until(EC.presence_of_element_located((By.XPATH, self.SEARCH_BRAND_INPUT)))
        time.sleep(1)
        print("Brand popup is open. Total brands:", self.get_brand_count())

    def apply_filters(self) -> None:
        self.wait.until(EC.element_to_be_clickable((By.XPATH, self.APPLY_FILTERS_BTN))).click()
        print("Filters applied.")
        time.sleep(3)

    # ---------- brand rows ----------
    def get_brand_count(self) -> int:
        return len(self.driver.find_elements(By.XPATH, self.BRAND_ROWS))

    def is_brand_checked(self, row_xpath: str) -> bool:
        boxes = self.driver.find_elements(By.XPATH, f'{row_xpath}//input[@type="checkbox"]')
        return bool(boxes) and boxes[0].is_selected()

    def click_row(self, row_xpath: str) -> None:
        row = self.wait.until(EC.presence_of_element_located((By.XPATH, row_xpath)))
        # inline='center' also scrolls the popup horizontally to reach later columns
        self.driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center', inline: 'center'});", row
        )
        time.sleep(0.5)
        try:
            ActionChains(self.driver).move_to_element(row).pause(0.3).click().perform()
        except StaleElementReferenceException:
            row = self.driver.find_element(By.XPATH, row_xpath)
            ActionChains(self.driver).move_to_element(row).pause(0.3).click().perform()
        time.sleep(1)

    def select_brand(self, number: int) -> str:
        """Select the brand at position `number` (1 = Apple, 2 = Google, ...)."""
        total = self.get_brand_count()
        if not 1 <= number <= total:
            raise ValueError(f"Brand number must be between 1 and {total}, got {number}")

        row_xpath = f"({self.BRAND_ROWS})[{number}]"
        name = self.driver.find_element(By.XPATH, row_xpath).get_attribute("title")

        if self.is_brand_checked(row_xpath):
            print(f"#{number} {name}: already selected, skipping.")
            return name

        self.click_row(row_xpath)
        if not self.is_brand_checked(row_xpath):  # one retry if the click didn't register
            self.click_row(row_xpath)

        print(f"#{number} {name}: selected = {self.is_brand_checked(row_xpath)}")
        return name

    def select_brands(self, *numbers: int) -> list:
        return [self.select_brand(n) for n in numbers]

    def scroll_and_get_html(self, url):
        """Open URL, scroll to the bottom and return HTML."""
        self.driver.get(url)
        print(f"Opened URL: {url}")

        time.sleep(3)

        previous_position = -1

        while True:
            metrics = self.driver.execute_script("""
                const element = document.scrollingElement;

                element.scrollTop = Math.min(
                    element.scrollTop + 700,
                    element.scrollHeight - element.clientHeight
                );

                return {
                    position: element.scrollTop,
                    max_position: element.scrollHeight - element.clientHeight
                };
            """)

            current_position = metrics["position"]
            max_position = metrics["max_position"]

            print(
                f"Scroll position: {current_position:.0f} / "
                f"{max_position:.0f}"
            )

            # Stop when the bottom is reached
            if current_position >= max_position - 1:
                break

            # Safety condition: prevent infinite loops
            if current_position == previous_position:
                break

            previous_position = current_position
            time.sleep(0.5)

        print("Reached page bottom.")

        html = self.driver.page_source
        print(f"HTML extracted: {len(html)} characters")

        return html

    def scroll_current_page(self):
        """Scroll the currently opened page to the bottom."""

        time.sleep(2)
        previous_position = -1

        while True:
            metrics = self.driver.execute_script("""
                const element = document.scrollingElement;

                element.scrollTop = Math.min(
                    element.scrollTop + 700,
                    element.scrollHeight - element.clientHeight
                );

                return {
                    position: element.scrollTop,
                    max_position: element.scrollHeight - element.clientHeight
                };
            """)

            current_position = metrics["position"]
            max_position = metrics["max_position"]

            print(f"Scroll: {current_position:.0f} / {max_position:.0f}")

            if current_position >= max_position - 1:
                break

            if current_position == previous_position:
                break

            previous_position = current_position
            time.sleep(0.5)

        print("Reached page bottom.")
        return self.driver.page_source

    def click_next_page(self):
        """Find and click the Next button."""

        next_xpath = (
            "//a[normalize-space()='Next'] | "
            "//button[normalize-space()='Next']"
        )

        next_buttons = self.driver.find_elements(By.XPATH, next_xpath)

        if not next_buttons:
            print("Next button not found. Stopping.")
            return False

        next_button = next_buttons[0]

        if not next_button.is_displayed() or not next_button.is_enabled():
            print("Next button is unavailable. Stopping.")
            return False

        old_url = self.driver.current_url

        self.driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'});",
            next_button
        )

        self.wait.until(
            EC.element_to_be_clickable((By.XPATH, next_xpath))
        )

        next_button.click()

        try:
            self.wait.until(lambda driver: driver.current_url != old_url)
            print("Next page opened:", self.driver.current_url)
            return True

        except Exception:
            print("Page URL did not change. Stopping.")
            return False

    def get_full_url(self, url):
        """Convert relative URL into a complete URL."""

        base_url = "https://www.flipkart.com"

        return urljoin(base_url, url)