#!/usr/bin/env python3
import base64
import json
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout

# --- SETTINGS ---
BASE_URL = "https://www.lacentrale.fr"
LISTING_URL = f"{BASE_URL}/listing"
MAX_ADS = 5  # Set the maximum number of ads you want to scrape.
MAX_PAGES = 40  # Set the maximum number of listing pages to check for ads.
CDP_URL = "http://127.0.0.1:9222" # Your Chrome debugging port
REQUEST_TIMEOUT_MS = 30000
SLEEP_MIN_SECONDS = 1.0
SLEEP_MAX_SECONDS = 2.5
# --- END SETTINGS ---

def ts() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def log_i(msg: str): print(f"[{ts()}] [info] {msg}")
def log_w(msg: str): print(f"[{ts()}] [warn] {msg}")
def log_e(msg: str): print(f"[{ts()}] [error] {msg}")

def polite_sleep(min_s: float = SLEEP_MIN_SECONDS, max_s: float = SLEEP_MAX_SECONDS):
    time.sleep(random.uniform(min_s, max_s))

def get_page_ad_urls(page_content: str) -> List[str]:
    """Finds ad URLs by looking for their specific HTML structure."""
    if not page_content: return []
    soup = BeautifulSoup(page_content, "html.parser")
    urls = set()
    ad_containers = soup.select("div[class*='searchCard']")
    for container in ad_containers:
        link_tag = container.find("a", href=True)
        if link_tag and link_tag["href"].startswith("/auto-occasion-annonce-"):
            urls.add(f"{BASE_URL}{link_tag['href']}")
    return sorted(list(urls))

def extract_ad_details(page: Page, url: str) -> Optional[Dict[str, Any]]:
    """
    Extracts ad details using a robust hybrid approach.
    1. Attempts to parse the clean __NEXT_DATA__ JSON.
    2. Supplements and falls back to scraping visible HTML elements.
    3. Clicks the button to reveal and capture the phone number.
    """
    details = {}
    try:
        # --- STAGE 1: Attempt to get structured data from __NEXT_DATA__ JSON ---
        next_data_script = page.locator("#__NEXT_DATA__").inner_text()
        if next_data_script:
            data = json.loads(next_data_script)
            apollo_state = data.get("props", {}).get("pageProps", {}).get("__APOLLO_STATE__", {})
            
            ad_data = None
            ad_id_from_url = url.split("-")[-1].replace(".html", "")
            # Construct the exact key to look for
            apollo_key = f'Ad:{ad_id_from_url}'
            if apollo_key in apollo_state:
                ad_data = apollo_state[apollo_key]

            if ad_data:
                vehicle = ad_data.get("vehicle", {})
                title_parts = [vehicle.get("make"), vehicle.get("model"), vehicle.get("version"), str(vehicle.get("year"))]
                details["name"] = " ".join(part for part in title_parts if part)
                details["price"] = ad_data.get("price")
                details["mileage"] = vehicle.get("mileage")
                details["technical_sheet_url"] = vehicle.get("technicalSheetUrl")
                details["seller_comment"] = ad_data.get("description")

                # Seller / Agency Info
                seller = ad_data.get("seller", {})
                if seller:
                    details["agency_name"] = seller.get("name")
                    details["agency_type"] = seller.get("type")

                # Main Features (Criterias)
                criterias = ad_data.get("criterias", [])
                details["features"] = ", ".join([c.get("label") for c in criterias if c.get("label")])

                # Equipment & Options
                equipments = vehicle.get("equipments", [])
                all_equipment = []
                if equipments:
                    for category in equipments:
                        if isinstance(category, dict) and "items" in category:
                            for item in category.get("items", []):
                                if isinstance(item, dict) and "label" in item:
                                    all_equipment.append(item.get("label"))
                details["equipment_and_options"] = ", ".join(all_equipment)

        # --- STAGE 2: Scrape visible HTML to supplement or fall back ---
        soup = BeautifulSoup(page.content(), "html.parser")

        if not details.get("name"):
            details["name"] = soup.find("h1").get_text(strip=True) if soup.find("h1") else "N/A"
        if not details.get("price"):
            price_el = soup.select_one("div[class*='PriceInformation_price__']")
            details["price"] = int("".join(re.findall(r'\d+', price_el.get_text()))) if price_el else "N/A"
        if not details.get("seller_comment"):
            desc_el = soup.select_one("div[data-test='description']")
            details["seller_comment"] = desc_el.get_text(strip=True) if desc_el else ""
        
        # --- STAGE 3: Actively click to reveal and get the phone number ---
        try:
            phone_button = page.locator("#phoneButtonId")
            if phone_button.is_visible():
                phone_button.click()
                # Wait for the link with "tel:" to appear, which holds the number
                phone_element = page.locator("a[href^='tel:']").first
                phone_element.wait_for(timeout=5000)
                phone_href = phone_element.get_attribute("href")
                details["phone_number"] = phone_href.replace("tel:", "") if phone_href else "Not found after click"
            else:
                details["phone_number"] = "Button not visible"
        except Exception as e:
            details["phone_number"] = "Error getting phone number"

        details["ad_url"] = url
        return details

    except Exception as e:
        log_e(f"CRITICAL ERROR processing {url}: {type(e).__name__}: {e}")
        return None

def main():
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(CDP_URL)
            context = browser.contexts[0]
            page = context.pages[0]
            log_i("Successfully connected to existing browser session.")
        except Exception:
            log_e(f"Could not connect to browser at {CDP_URL}. Make sure Chrome is running with --remote-debugging-port=9222")
            return

        # Part 1: Discover all Ad URLs
        all_ad_urls = set()
        for page_num in range(1, MAX_PAGES + 1):
            if len(all_ad_urls) >= MAX_ADS: break
            current_url = f"{LISTING_URL}?page={page_num}"
            log_i(f"Discovering URLs on listing page {page_num}...")
            try:
                page.goto(current_url, wait_until="domcontentloaded", timeout=REQUEST_TIMEOUT_MS)
                new_urls = set(get_page_ad_urls(page.content()))
                if not new_urls: log_w(f"No URLs found on page {page_num}. Stopping."); break
                added_urls = new_urls - all_ad_urls
                if not added_urls: log_w(f"No new URLs found on page {page_num}. Stopping."); break
                all_ad_urls.update(added_urls)
                log_i(f"Found {len(added_urls)} new URLs. Total collected: {len(all_ad_urls)}")
            except Exception as e:
                log_e(f"Error on listing page {current_url}: {e}")
        
        # Part 2: Scrape details for each Ad
        final_ad_urls = sorted(list(all_ad_urls))[:MAX_ADS]
        log_i(f"Finished discovery. Proceeding to scrape {len(final_ad_urls)} ads.")
        if not final_ad_urls: return

        all_rows = []
        for url in final_ad_urls:
            log_i(f"Scraping ad: {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=REQUEST_TIMEOUT_MS)
                details = extract_ad_details(page, url)
                if details:
                    all_rows.append(details)
                    log_i(f"SUCCESS: Extracted data for: {details.get('name')}")
                else:
                    log_w(f"FAILURE: No details extracted for: {url}")
            except Exception as e:
                log_e(f"Failed to process URL {url}: {e}")
            polite_sleep()

        # Part 3: Save to Excel
        if not all_rows:
            log_w("No data was extracted. Excel file will not be created.")
            return

        df = pd.DataFrame(all_rows)
        out_path = "lacentrale_listings_complete.xlsx"
        df.to_excel(out_path, index=False)
        log_i(f"✅ Scraping complete. Saved {len(df)} rows to {out_path}")

if __name__ == "__main__":
    main()