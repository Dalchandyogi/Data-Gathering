
from bs4 import BeautifulSoup


def scrape_phone_list(helpers):

    all_products = []
    seen_urls = set()
    page_number = 1

    while True:

        print(f"\n========== PAGE {page_number} ==========")

        # Scroll and extract current page HTML
        html = helpers.scroll_current_page()

        soup = BeautifulSoup(html, "html.parser")

        all_phones_divs = soup.find_all(
            "div",
            class_="lvJbLV col-12-12"
        )

        print("Total containers:", len(all_phones_divs))

        new_products = 0

        for phone in all_phones_divs:

            # Extract product name
            name_tag = phone.find("div", class_="RG5Slk")

            # Skip containers without a product name
            if not name_tag:
                continue

            phone_name = name_tag.get_text(strip=True)

            # Extract product URL
            link_tag = phone.find("a", class_="k7wcnx")

            if not link_tag or not link_tag.get("href"):
                continue

            product_url = helpers.get_full_url(link_tag.get("href"))

            # Extract price
            price_tag = phone.select_one("div.hZ3P6w.DeU9vF")
            price = price_tag.get_text(strip=True) if price_tag else None

            # Extract rating
            rating_tag = phone.find("div", class_="MKiFS6")
            rating = rating_tag.get_text(strip=True) if rating_tag else None

            if product_url in seen_urls:
                continue

            seen_urls.add(product_url)
            new_products += 1

            all_products.append({
                "name": phone_name,
                "url": product_url,
                "price": price,
                "rating": rating
            })

            print(
                f"{len(all_products)}. {phone_name} | "
                f"{price} | {rating}"
            )

        print("New products on this page:", new_products)

        # Stop if no new products
        if new_products == 0:
            print("No new products found. Stopping.")
            break

        # Go to next page
        if not helpers.click_next_page():
            break

        page_number += 1

    print("\n========== LIST SCRAPING COMPLETED ==========")
    print("Total pages visited:", page_number)
    print("Total unique products:", len(all_products))

    return all_products
