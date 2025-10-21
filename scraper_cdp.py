#!/usr/bin/env python3
import base64
import json
import os
import random
import re
import time
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union
from urllib.parse import urlparse

import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE_URL = "https://www.lacentrale.fr"
LISTING_URL = f"{BASE_URL}/listing"

# Limits and pacing
MAX_ADS = 40
MAX_PAGES = 40
BATCH_SIZE = 20            # run in small batches to avoid rate spikes
COOLDOWN_SECONDS = 30      # suggested cooldown between batches
REQUEST_TIMEOUT_MS = 40000
SLEEP_MIN_SECONDS = 1.5
SLEEP_MAX_SECONDS = 3.2
CLICK_WAIT_MIN = 0.6
CLICK_WAIT_MAX = 1.4

DEBUG_DIR = "./debug_http"
DEBUG_SNIPPET_CHARS = 1800
CDP_URL = "http://127.0.0.1:9222"

AD_URL_RE_ABS = re.compile(r"^https?://(?:www\.)?lacentrale\.fr/auto-occasion-annonce-\d+\.html$", re.IGNORECASE)
AD_URL_RE_REL = re.compile(r"^/auto-occasion-annonce-\d+\.html$", re.IGNORECASE)

def ts() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + "Z"

def log_i(m: str) -> None:
    print(f"[info] {m}")

def log_w(m: str) -> None:
    print(f"[warn] {m}")

def log_d(m: str) -> None:
    print(f"[debug] {ts()} {m}")

def ensure_debug_dir() -> None:
    if not os.path.isdir(DEBUG_DIR):
        os.makedirs(DEBUG_DIR, exist_ok=True)

def save_debug_html(name: str, content: str) -> str:
    ensure_debug_dir()
    path = os.path.join(DEBUG_DIR, name)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path
    except Exception as exc:
        log_w(f"Failed to save debug HTML '{name}': {exc}")
        return ""

def save_debug_json(name: str, data: Any) -> str:
    ensure_debug_dir()
    path = os.path.join(DEBUG_DIR, name)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return path
    except Exception as exc:
        log_w(f"Failed to save debug JSON '{name}': {exc}")
        return ""

def polite_sleep(a: float = None, b: float = None) -> None:
    lo = SLEEP_MIN_SECONDS if a is None else a
    hi = SLEEP_MAX_SECONDS if b is None else b
    time.sleep(random.uniform(lo, hi))

def human_wiggle(page) -> None:
    try:
        x = random.randint(120, 900); y = random.randint(120, 700)
        page.mouse.move(x, y, steps=random.randint(6, 14))
        time.sleep(random.uniform(0.08, 0.22))
    except Exception:
        pass

def human_scroll(page, times: int = None) -> None:
    try:
        n = times if times is not None else random.randint(2, 5)
        for _ in range(n):
            page.mouse.wheel(0, random.randint(250, 900))
            time.sleep(random.uniform(0.25, 0.65))
    except Exception:
        pass

def is_block_page(html: str) -> bool:
    l = (html or "").lower()
    return (
        "you've been blocked" in l
        or "access blocked" in l
        or "captcha" in l
        or "captcha-delivery" in l
        or "datadome" in l
        or "please enable js" in l
        or "unusual activity" in l
    )

def to_abs(url: str) -> str:
    if not url:
        return ""
    if url.startswith("/"):
        return f"{BASE_URL}{url}"
    return url

def is_ad_url(u: str) -> bool:
    if not u:
        return False
    return bool(AD_URL_RE_ABS.match(u) or AD_URL_RE_REL.match(u))

def parse_next_data_from_html(html: str) -> Optional[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("script", id="__NEXT_DATA__")
    if not tag:
        return None
    raw = (tag.string or tag.text or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception as exc:
        log_w(f"Failed to parse __NEXT_DATA__: {exc}")
        return None

def walk_json(obj: Any) -> Iterable[Any]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk_json(v)
    elif isinstance(obj, list):
        for it in obj:
            yield from walk_json(it)

def find_first_by_key_names(root: Any, keys: List[str], expect_types: Union[type, tuple] = (str, int, float, list, dict)) -> Optional[Any]:
    keys_lower = {k.lower() for k in keys}
    for node in walk_json(root):
        if isinstance(node, dict):
            for k, v in node.items():
                if k.lower() in keys_lower and isinstance(v, expect_types):
                    return v
    return None

def find_first_string_by_key_contains(root: Any, substrings: List[str]) -> Optional[str]:
    subs_lower = [s.lower() for s in substrings]
    for node in walk_json(root):
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, str):
                    k_l = k.lower()
                    if any(s in k_l for s in subs_lower):
                        return v
    return None

def find_all_list_items_by_key_contains(root: Any, substrings: List[str]) -> List[str]:
    subs_lower = [s.lower() for s in substrings]
    results: List[str] = []
    for node in walk_json(root):
        if isinstance(node, dict):
            for k, v in node.items():
                k_l = k.lower()
                if any(s in k_l for s in subs_lower):
                    if isinstance(v, list):
                        for it in v:
                            if isinstance(it, str):
                                results.append(it)
                            elif isinstance(it, dict):
                                label = it.get("label") or it.get("name") or it.get("title")
                                if isinstance(label, str):
                                    results.append(label)
                    elif isinstance(v, str):
                        results.append(v)
    seen = set()
    out: List[str] = []
    for x in results:
        n = (x or "").strip()
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out

def try_decode_base64_to_str(value: str) -> Optional[str]:
    s = (value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9+/=]+", s):
        return None
    pad = (-len(s)) % 4
    if pad:
        s += "=" * pad
    try:
        decoded = base64.b64decode(s, validate=False).decode("utf-8", "ignore").strip()
        return decoded or None
    except Exception:
        return None

def extract_phone(root: Any) -> Optional[str]:
    direct = find_first_string_by_key_contains(root, ["phone", "tel", "telephone", "call"])
    cands: List[str] = []
    if isinstance(direct, str):
        cands.append(direct)
    for node in walk_json(root):
        if isinstance(node, dict):
            for k, v in node.items():
                k_l = k.lower()
                if any(s in k_l for s in ["phone", "tel", "telephone", "call"]):
                    if isinstance(v, str):
                        dec = try_decode_base64_to_str(v)
                        if dec:
                            cands.append(dec)
                if k_l in ("value", "number", "contact"):
                    if isinstance(v, str):
                        dec = try_decode_base64_to_str(v)
                        if dec:
                            cands.append(dec)
    for c in cands:
        m = re.findall(r"\+?\d[\d\-\.\s\(\)]{7,}", c or "")
        if m:
            return re.sub(r"[^\d+]", "", m[0]) or c
    for c in cands:
        cl = re.sub(r"[^\d+]", "", c or "")
        if len(cl) >= 8:
            return cl
    return None

def extract_price(root: Any) -> Optional[int]:
    c = find_first_by_key_names(root, ["price", "amount", "sellingPrice", "totalPrice", "priceRaw"], (int, float, str, dict))
    if isinstance(c, dict):
        for k in ("amount", "value", "price"):
            v = c.get(k)
            if isinstance(v, (int, float)):
                return int(v)
            if isinstance(v, str):
                d = re.sub(r"[^\d]", "", v)
                if d.isdigit():
                    return int(d)
    if isinstance(c, (int, float)):
        return int(c)
    if isinstance(c, str):
        d = re.sub(r"[^\d]", "", c)
        if d.isdigit():
            return int(d)
    for node in walk_json(root):
        if isinstance(node, str) and ("€" in node or "EUR" in (node or "").upper()):
            d = re.sub(r"[^\d]", "", node)
            if d.isdigit() and len(d) >= 3:
                return int(d)
    return None

def extract_title(root: Any) -> Optional[str]:
    for k in ["title", "adTitle", "vehicleTitle", "name"]:
        v = find_first_by_key_names(root, [k], (str,))
        if isinstance(v, str) and len(v.strip()) >= 3:
            return v.strip()
    return None

def extract_mileage_km(root: Any) -> Optional[int]:
    for k in ["mileageInKm", "mileage", "kilometrage", "kilometers", "km", "kilometrageInKm"]:
        v = find_first_by_key_names(root, [k], (int, float, str))
        if isinstance(v, (int, float)) and v > 0:
            return int(v)
        if isinstance(v, str):
            d = re.sub(r"[^\d]", "", v)
            if d.isdigit():
                val = int(d)
                if val > 0:
                    return val
    return None

def extract_warranty(root: Any) -> Optional[str]:
    items = find_all_list_items_by_key_contains(root, ["warranty", "garantie", "guarantee"])
    if items:
        return "; ".join(items)
    v = find_first_string_by_key_contains(root, ["warranty", "garantie", "guarantee"])
    return v.strip() if v else None

def extract_equipment_and_options(root: Any) -> Optional[str]:
    items = find_all_list_items_by_key_contains(root, ["equipment", "equipments", "equipements", "options", "option"])
    return "; ".join(items) if items else None

def extract_guarantees_and_insurance(root: Any) -> Optional[str]:
    items = find_all_list_items_by_key_contains(root, ["guarantee", "garantie", "insurance", "assurance"])
    if items:
        return "; ".join(items)
    v = find_first_string_by_key_contains(root, ["guarantee", "garantie", "insurance", "assurance"])
    return v.strip() if v else None

def extract_technical_sheet_url(root: Any) -> Optional[str]:
    pat = re.compile(r"fiche[\-_]?technique", re.IGNORECASE)
    for node in walk_json(root):
        if isinstance(node, str) and node.startswith("http") and pat.search(node):
            return node
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, str) and v.startswith("http") and pat.search(v):
                    return v
                if k.lower() in ("href", "url") and isinstance(v, str) and v.startswith("http") and pat.search(v):
                    return v
    return None

def extract_from_ad_json(next_data: Dict[str, Any]) -> Dict[str, Optional[Union[str, int]]]:
    cands = [
        next_data.get("props", {}).get("pageProps", {}),
        next_data.get("pageProps", {}),
        next_data,
    ]
    root: Dict[str, Any] = {}
    for c in cands:
        if isinstance(c, dict) and c:
            root = c
            break
    adv = find_first_by_key_names(root, ["ad", "advert", "advertisement", "vehicle"], (dict,))
    if isinstance(adv, dict):
        root = adv
    return {
        "title": extract_title(root),
        "price_eur": extract_price(root),
        "phone": extract_phone(root),
        "warranty": extract_warranty(root),
        "mileage_km": extract_mileage_km(root),
        "technical_sheet_url": extract_technical_sheet_url(root),
        "equipment_options": extract_equipment_and_options(root),
        "guarantees_insurance": extract_guarantees_and_insurance(root),
    }

def _parse_classified_main_infos(html: str) -> Optional[Dict[str, Any]]:
    try:
        m = re.search(r"var\s+CLASSIFIED_MAIN_INFOS\s*=\s*(\{[\s\S]*?\})\s*;", html)
        if not m:
            return None
        blob = m.group(1)
        # Ensure valid JSON by stripping trailing commas if any (best-effort)
        # Most pages ship valid JSON already.
        return json.loads(blob)
    except Exception:
        return None

def _parse_summary_information_data(html: str) -> Optional[Dict[str, Any]]:
    try:
        m = re.search(r"var\s+SummaryInformationData\s*=\s*(\{[\s\S]*?\})\s*;", html)
        if not m:
            return None
        blob = m.group(1)
        return json.loads(blob)
    except Exception:
        return None

def _reveal_phone_number(page) -> Optional[str]:
    """
    Click the phone button to reveal the phone number and extract it.
    """
    try:
        # Look for the phone button with the specific selector
        phone_button = page.query_selector('button[data-testid="button"][data-page-zone="telephone"][id="summary-contact-phone"]')
        if not phone_button:
            # Try alternative selectors
            phone_button = page.query_selector('button[id="summary-contact-phone"]')
        if not phone_button:
            phone_button = page.query_selector('button[data-page-zone="telephone"]')
        
        if phone_button:
            log_d("Found phone button, clicking to reveal phone number...")
            phone_button.click()
            
            # Wait a moment for the phone number to appear
            page.wait_for_timeout(1000)
            
            # Look for the revealed phone number in various possible locations
            phone_selectors = [
                'span:has-text("02")',  # French phone numbers start with 02, 03, 04, 05, 06, 07, 08, 09
                'span:has-text("03")',
                'span:has-text("04")',
                'span:has-text("05")',
                'span:has-text("06")',
                'span:has-text("07")',
                'span:has-text("08")',
                'span:has-text("09")',
                '#contactInfoWrapper span',
                '.ContactInformation_phone__qlEra span',
                'button[data-page-zone="telephone"] + span',
                'button[data-page-zone="telephone"] span span'
            ]
            
            for selector in phone_selectors:
                try:
                    phone_element = page.query_selector(selector)
                    if phone_element:
                        phone_text = phone_element.inner_text().strip()
                        # Check if it looks like a phone number (contains digits and spaces)
                        if re.search(r'\d{2}\s+\d{2}\s+\d{2}\s+\d{2}', phone_text):
                            # Clean up the phone number (remove spaces)
                            phone_clean = re.sub(r'\s+', '', phone_text)
                            log_d(f"Phone number revealed: {phone_clean}")
                            return phone_clean
                except Exception as e:
                    log_d(f"Error checking selector {selector}: {e}")
                    continue
            
            # If no specific selector worked, try to find any span with a phone-like pattern
            try:
                all_spans = page.query_selector_all('span')
                for span in all_spans:
                    text = span.inner_text().strip()
                    if re.search(r'\d{2}\s+\d{2}\s+\d{2}\s+\d{2}', text):
                        phone_clean = re.sub(r'\s+', '', text)
                        log_d(f"Phone number found in span: {phone_clean}")
                        return phone_clean
            except Exception as e:
                log_d(f"Error searching all spans: {e}")
        
        log_d("No phone button found or phone number not revealed")
        return None
        
    except Exception as e:
        log_d(f"Error revealing phone number: {e}")
        return None

def extract_ad_details(page_content: str, url: str) -> Dict[str, Optional[Union[str, int]]]:
    """
    Parse <script id="__NEXT_DATA__"> and extract details from props.pageProps.ad
    per the required mapping. Robust to missing fields.
    """
    result: Dict[str, Optional[Union[str, int]]] = {
        "title": None,
        "price_eur": None,
        "mileage_km": None,
        # removed warranty/guarantees from output
        "equipment_options": None,
        "phone": None,
        "features": None,
        "seller_comment": None,
        "agency_name": None,
        "characteristics": None,
        "address": None,
        "ad_url": url,
    }

    try:
        soup = BeautifulSoup(page_content, "html.parser")
        
        # Try to find the actual data in script blocks first
        classified_main_infos = _parse_classified_main_infos(page_content)
        summary_info = _parse_summary_information_data(page_content)
        
        if classified_main_infos or summary_info:
            log_d(f"Found data in script blocks for {url}")
            # Save debug JSON for first few ads to understand structure
            if "debug_json" not in globals():
                globals()["debug_json"] = 0
            if globals()["debug_json"] < 3:
                debug_data = {
                    "classified_main_infos": classified_main_infos,
                    "summary_info": summary_info
                }
                save_debug_json(f"script_data_{globals()['debug_json']}.json", debug_data)
                globals()["debug_json"] += 1
        else:
            # Fallback to __NEXT_DATA__ if script blocks not found
            tag = soup.find("script", id="__NEXT_DATA__")
            if not tag:
                log_w(f"No data found in script blocks or __NEXT_DATA__ for {url}")
                return result
            raw = (tag.string or tag.text or "").strip()
            if not raw:
                log_w(f"Empty __NEXT_DATA__ script tag for {url}")
                return result
            data = json.loads(raw)
            log_d(f"Successfully parsed __NEXT_DATA__ for {url}")
            
            # Save debug JSON for first few ads to understand structure
            if "debug_json" not in globals():
                globals()["debug_json"] = 0
            if globals()["debug_json"] < 3:
                save_debug_json(f"next_data_{globals()['debug_json']}.json", data)
                globals()["debug_json"] += 1
            
    except Exception as exc:
        log_w(f"Failed to parse data for {url}: {exc}")
        return result

    try:
        # Use script block data if available, otherwise fallback to __NEXT_DATA__
        if classified_main_infos or summary_info:
            log_d(f"Using script block data for {url}")
            
            # Extract from CLASSIFIED_MAIN_INFOS
            if classified_main_infos:
                try:
                    classified = classified_main_infos.get("data", {}).get("classified", {})
                    vehicle = classified_main_infos.get("data", {}).get("vehicle", {})
                    strengths = classified_main_infos.get("data", {}).get("strengths", [])

                    # Title
                    title_parts: List[str] = []
                    for p in [classified.get("title"), vehicle.get("label"), vehicle.get("make"), vehicle.get("model"), classified.get("year")]:
                        if isinstance(p, str) and p.strip():
                            title_parts.append(p.strip())
                    result["title"] = " ".join(dict.fromkeys([p for p in title_parts if p])) or None

                    # Price & mileage
                    price = classified.get("price")
                    if isinstance(price, (int, float)):
                        result["price_eur"] = int(price)
                    mileage = classified.get("mileage")
                    if isinstance(mileage, (int, float)):
                        result["mileage_km"] = int(mileage)

                    # Equipment & options
                    eq_labels: List[str] = []
                    eq = vehicle.get("equipments") or []
                    if isinstance(eq, list):
                        for it in eq:
                            if isinstance(it, dict):
                                lab = it.get("label")
                                if isinstance(lab, str) and lab.strip():
                                    eq_labels.append(lab.strip())
                            elif isinstance(it, str) and it.strip():
                                eq_labels.append(it.strip())
                            if eq_labels:
                                result["equipment_options"] = " | ".join(dict.fromkeys(eq_labels))

                    # Features (label: value)
                    feats: List[str] = []
                    if isinstance(strengths, list):
                        for s in strengths:
                            if not isinstance(s, dict):
                                continue
                            lab = s.get("label"); val = s.get("value")
                            if isinstance(lab, str) and lab.strip():
                                if isinstance(val, str) and val.strip():
                                    feats.append(f"{lab.strip()}: {val.strip()}")
                                else:
                                    feats.append(lab.strip())
                    if feats:
                        result["features"] = " | ".join(feats)

                    # Seller comment (HTML -> text)
                    desc = classified.get("description", {}).get("content")
                    if isinstance(desc, str) and desc:
                        try:
                            soup = BeautifulSoup(desc, "html.parser")
                            txt = soup.get_text("\n", strip=True)
                            if txt:
                                result["seller_comment"] = txt
                        except Exception:
                            pass

                    log_d(f"CLASSIFIED_MAIN_INFOS extraction result: title={result['title']}, price={result['price_eur']}, mileage={result['mileage_km']}")
                except Exception as exc:
                    log_w(f"CLASSIFIED_MAIN_INFOS extraction failed: {exc}")

            # Extract from SummaryInformationData
            if summary_info:
                try:
                    # Agency name
                    seller_infos = summary_info.get("sellerInfos", {})
                    if isinstance(seller_infos, dict):
                        seller_name = seller_infos.get("sellerName")
                        if isinstance(seller_name, str) and seller_name.strip():
                            result["agency_name"] = seller_name.strip()

                    # Phone number from SummaryInformationData - look in different locations
                    # Try to find phone in various possible locations
                    phone_found = False
                    
                    # Check if there's a phone field directly in sellerInfos
                    if isinstance(seller_infos, dict) and seller_infos.get("phone"):
                        phone = seller_infos.get("phone")
                        if isinstance(phone, str) and phone.strip():
                            result["phone"] = phone.strip().replace(" ", "")
                            phone_found = True
                    
                    # Check in classified data
                    if not phone_found:
                        classified_data = summary_info.get("classified", {})
                        if isinstance(classified_data, dict):
                            # Try to find phone in contacts
                            contacts = classified_data.get("contacts", {})
                            if isinstance(contacts, dict):
                                for key, contact in contacts.items():
                                    if isinstance(contact, dict) and contact.get("phone"):
                                        phone = contact.get("phone")
                                        if isinstance(phone, str) and phone.strip():
                                            result["phone"] = phone.strip().replace(" ", "")
                                            phone_found = True
                                            break

                    # Address extraction from sellerInfos
                    if isinstance(seller_infos, dict):
                        address_parts = []
                        address_obj = seller_infos.get("address", {})
                        if isinstance(address_obj, dict):
                            street = address_obj.get("street1")
                            city = address_obj.get("city")
                            zip_code = address_obj.get("zipCode")
                            country = address_obj.get("country")
                            
                            if street:
                                address_parts.append(street)
                            if city and zip_code:
                                address_parts.append(f"{zip_code} {city}")
                            elif city:
                                address_parts.append(city)
                            if country and country != "FRANCE":
                                address_parts.append(country)
                        
                        if address_parts:
                            result["address"] = ", ".join(address_parts)

                    log_d(f"SummaryInformationData extraction result: agency_name={result['agency_name']}, phone={result['phone']}, address={result['address']}")
                except Exception as exc:
                    log_w(f"SummaryInformationData extraction failed: {exc}")

            # Extract phone number from CLASSIFIED_MORE_INFOS if not found in SummaryInformationData
            if not result.get("phone") and classified_main_infos:
                try:
                    # Check if there's a CLASSIFIED_MORE_INFOS script block with phone data
                    # This is a separate script block that contains showroom contact info
                    more_infos_script = None
                    soup = BeautifulSoup(page_content, "html.parser")
                    for script in soup.find_all("script"):
                        if script.string and ("CLASSIFIED_MORE_INFOS" in script.string or "classified_more_infos" in script.string):
                            more_infos_script = script.string
                            break
                    
                    if more_infos_script:
                        # Extract CLASSIFIED_MORE_INFOS data
                        m = re.search(r"var\s+CLASSIFIED_MORE_INFOS\s*=\s*(\{[\s\S]*?\})\s*$", more_infos_script, re.MULTILINE)
                        if m:
                            try:
                                more_infos_data = json.loads(m.group(1))
                                # Look for phone in showroom contacts
                                data = more_infos_data.get("data", {})
                                seller_infos = data.get("sellerInfos", {})
                                showroom = seller_infos.get("showroom", {})
                                contacts = showroom.get("contacts", [])
                                
                                if isinstance(contacts, list) and contacts:
                                    for contact in contacts:
                                        if isinstance(contact, dict) and contact.get("phone"):
                                            phone = contact.get("phone")
                                            if isinstance(phone, str) and phone.strip():
                                                result["phone"] = phone.strip().replace(" ", "")
                                                log_d(f"Phone extracted from CLASSIFIED_MORE_INFOS: {result['phone']}")
                                                break
                            except Exception as exc:
                                log_w(f"Failed to parse CLASSIFIED_MORE_INFOS: {exc}")
                except Exception as exc:
                    log_w(f"CLASSIFIED_MORE_INFOS phone extraction failed: {exc}")

            # Extract characteristics from script block data
            if summary_info:
                try:
                    def gv(obj: Dict[str, Any], path: List[str]) -> Optional[Any]:
                        cur: Any = obj
                        for p in path:
                            if not isinstance(cur, dict):
                                return None
                            cur = cur.get(p)
                        return cur
                    
                    # Get vehicle specs from SummaryInformationData
                    vehicle_specs = gv(summary_info, ["classified", "vehicle", "combined", "specs"])
                    vehicle_version = gv(summary_info, ["classified", "vehicle", "combined", "version"])
                    
                    if isinstance(vehicle_specs, dict):
                        parts: List[str] = []
                        mapping = [
                            ("Boîte de vitesse", ["gearbox"]),
                            ("Énergie", ["energy"]),
                            ("Nombre de portes", ["nbOfDoors"]),
                            ("Nombre de places", ["seatingCapacity"]),
                            ("Puissance fiscale", ["fiscalHorsePower"]),
                            ("Puissance DIN", ["powerDin"]),
                            ("Norme euro", ["critair","standardMet"]),
                            ("Crit'Air", ["critair","critairLevel"]),
                            ("Consommation", ["consumption","consumption120"]),
                            ("Emission de CO2", ["co2","combined"]),
                            ("Cylindrée", ["cubic"]),
                            ("Longueur", ["length"]),
                            ("Largeur", ["width"]),
                            ("Hauteur", ["height"]),
                            ("Poids", ["weight"]),
                            ("Volume coffre max", ["maxTrunkVolume"]),
                            ("Garantie", ["warranty"]),
                        ]
                        for label, path in mapping:
                            val = gv(vehicle_specs, path)
                            if val is not None:
                                parts.append(f"{label}: {val}")
                        
                        # Add version info
                        if isinstance(vehicle_version, dict):
                            for key, label in [("make", "Marque"), ("model", "Modèle"), ("commercialModel", "Modèle commercial"), ("trimLevel", "Finition")]:
                                val = vehicle_version.get(key)
                                if val is not None:
                                    parts.append(f"{label}: {val}")
                        
                        # Add first traffic date
                        first_traffic = gv(summary_info, ["classified", "vehicle", "combined", "firstTrafficDate"])
                        if first_traffic:
                            parts.append(f"Mise en circulation: {first_traffic}")
                        
                        if parts:
                            result["characteristics"] = " | ".join(parts)
                            log_d(f"Characteristics extracted from SummaryInformationData: {len(parts)} fields")
                except Exception as exc:
                    log_w(f"SummaryInformationData characteristics extraction failed: {exc}")

            # If we have data from script blocks, return early
            if result.get("title") or result.get("price_eur"):
                return result
        else:
            # Fallback to __NEXT_DATA__ parsing (original logic)
            log_d(f"Using __NEXT_DATA__ fallback for {url}")
            data = json.loads((soup.find("script", id="__NEXT_DATA__").string or "").strip())
            
            # First try the standard path
            ad = (data.get("props", {}).get("pageProps", {}).get("ad", {}))
            log_d(f"Standard ad path result: {type(ad)} - {bool(ad)}")
            
            if not isinstance(ad, dict) or not ad:
                # Try dynamic container keys like "Ad:69117177614"
                try:
                    def _find_dynamic_ad_container(node: Any) -> Optional[Dict[str, Any]]:
                        if isinstance(node, dict):
                            for k, v in node.items():
                                if isinstance(k, str) and re.match(r"^Ad:\d+", k) and isinstance(v, dict):
                                    return v
                            for v in node.values():
                                res = _find_dynamic_ad_container(v)
                                if res:
                                    return res
                        elif isinstance(node, list):
                            for it in node:
                                res = _find_dynamic_ad_container(it)
                                if res:
                                    return res
                        return None
                    dyn = _find_dynamic_ad_container(data)
                    if isinstance(dyn, dict):
                        ad = dyn
                        log_d(f"Found dynamic ad container: {type(ad)}")
                except Exception as exc:
                    log_d(f"Dynamic ad container search failed: {exc}")
                    pass
                    
            if not isinstance(ad, dict) or not ad:
                log_w(f"No ad data found in __NEXT_DATA__ for {url}")
                return result
            vehicle = ad.get("vehicle", {}) or {}

        # Title from make, model, version, year
        try:
            parts: List[str] = []
            make = vehicle.get("make")
            model = vehicle.get("model")
            version = vehicle.get("version")
            year = vehicle.get("year")
            for p in (make, model, version, str(year) if year is not None else None):
                if isinstance(p, str) and p.strip():
                    parts.append(p.strip())
            result["title"] = " ".join(parts) if parts else None
        except Exception:
            pass

        # Price
        try:
            price = ad.get("price")
            if isinstance(price, (int, float)):
                result["price_eur"] = int(price)
            elif isinstance(price, str):
                digits = re.sub(r"[^\d]", "", price)
                if digits.isdigit():
                    result["price_eur"] = int(digits)
        except Exception:
            pass

        # Mileage
        try:
            mileage = vehicle.get("mileage")
            if isinstance(mileage, (int, float)):
                result["mileage_km"] = int(mileage)
            elif isinstance(mileage, str):
                digits = re.sub(r"[^\d]", "", mileage)
                if digits.isdigit():
                    result["mileage_km"] = int(digits)
        except Exception:
            pass

        # Warranty intentionally omitted per requirements

        # Equipment & Options labels
        try:
            equipments = vehicle.get("equipments") or []
            labels: List[str] = []
            if isinstance(equipments, list):
                for cat in equipments:
                    if isinstance(cat, dict):
                        # Shape A: flat dicts with a label
                        lab = cat.get("label")
                        if isinstance(lab, str) and lab.strip():
                            labels.append(lab.strip())
                        # Shape B: categorized with items
                        items = cat.get("items") or []
                        if isinstance(items, list):
                            for it in items:
                                if not isinstance(it, dict):
                                    continue
                                lab = it.get("label")
                                if isinstance(lab, str) and lab.strip():
                                    labels.append(lab.strip())
            if labels:
                seen: set[str] = set()
                uniq: List[str] = []
                for l in labels:
                    if l not in seen:
                        seen.add(l)
                        uniq.append(l)
                        result["equipment_options"] = " | ".join(uniq)
        except Exception:
            pass

        # NEW: Agency name and address from SummaryInformationData.sellerInfos
        try:
            # Parse from __NEXT_DATA__ scripts in fallback path
            summary_obj = None
            scripts = (data.get("props", {}).get("pageProps", {}) or {}).get("scripts", [])
            if isinstance(scripts, list):
                for s in scripts:
                    if not isinstance(s, dict):
                        continue
                    if s.get("name") == "classified_summary_info":
                        content = s.get("content") or ""
                        m = re.search(r"var\s+SummaryInformationData\s*=\s*(\{[\s\S]*?\})\s*;", content)
                        if m:
                            try:
                                summary_obj = json.loads(m.group(1))
                            except Exception:
                                pass
                        break
                            
            if isinstance(summary_obj, dict):
                seller_infos = summary_obj.get("sellerInfos", {})
                if isinstance(seller_infos, dict):
                    # Agency name
                    sn = seller_infos.get("sellerName")
                    if isinstance(sn, str) and sn.strip():
                        result["agency_name"] = sn.strip()
                    else:
                        # Fallback: try to find seller name in other parts of the data
                        for key in ["name", "title", "label", "companyName"]:
                            val = seller_infos.get(key)
                            if isinstance(val, str) and val.strip():
                                result["agency_name"] = val.strip()
                                break
                    
                    # Address extraction
                    address_parts = []
                    address_obj = seller_infos.get("address", {})
                    if isinstance(address_obj, dict):
                        street = address_obj.get("street1")
                        city = address_obj.get("city")
                        zip_code = address_obj.get("zipCode")
                        country = address_obj.get("country")
                        
                        if street:
                            address_parts.append(street)
                        if city and zip_code:
                            address_parts.append(f"{zip_code} {city}")
                        elif city:
                            address_parts.append(city)
                        if country and country != "FRANCE":
                            address_parts.append(country)
                    
                    if address_parts:
                        result["address"] = ", ".join(address_parts)
        except Exception:
            pass

        # NEW: Characteristics assembled from SummaryInformationData.classified.vehicle.combined.specs
        try:
            def gv(obj: Dict[str, Any], path: List[str]) -> Optional[Any]:
                cur: Any = obj
                for p in path:
                    if not isinstance(cur, dict):
                        return None
                    cur = cur.get(p)
                return cur
            
            # Try SummaryInformationData first (this has the most complete data)
            if summary_obj:
                try:
                    # Get vehicle specs from SummaryInformationData
                    vehicle_specs = gv(summary_obj, ["classified", "vehicle", "combined", "specs"])
                    vehicle_version = gv(summary_obj, ["classified", "vehicle", "combined", "version"])
                    
                    if isinstance(vehicle_specs, dict):
                        parts: List[str] = []
                        mapping = [
                            ("Boîte de vitesse", ["gearbox"]),
                            ("Énergie", ["energy"]),
                            ("Nombre de portes", ["nbOfDoors"]),
                            ("Nombre de places", ["seatingCapacity"]),
                            ("Puissance fiscale", ["fiscalHorsePower"]),
                            ("Puissance DIN", ["powerDin"]),
                            ("Norme euro", ["critair","standardMet"]),
                            ("Crit'Air", ["critair","critairLevel"]),
                            ("Consommation", ["consumption","consumption120"]),
                            ("Emission de CO2", ["co2","combined"]),
                            ("Cylindrée", ["cubic"]),
                            ("Longueur", ["length"]),
                            ("Largeur", ["width"]),
                            ("Hauteur", ["height"]),
                            ("Poids", ["weight"]),
                            ("Volume coffre max", ["maxTrunkVolume"]),
                            ("Garantie", ["warranty"]),
                        ]
                        for label, path in mapping:
                            val = gv(vehicle_specs, path)
                            if val is not None:
                                parts.append(f"{label}: {val}")
                        
                        # Add version info
                        if isinstance(vehicle_version, dict):
                            for key, label in [("make", "Marque"), ("model", "Modèle"), ("commercialModel", "Modèle commercial"), ("trimLevel", "Finition")]:
                                val = vehicle_version.get(key)
                                if val is not None:
                                    parts.append(f"{label}: {val}")
                        
                        # Add first traffic date
                        first_traffic = gv(summary_info, ["classified", "vehicle", "combined", "firstTrafficDate"])
                        if first_traffic:
                            parts.append(f"Mise en circulation: {first_traffic}")
                        
                        if parts:
                            result["characteristics"] = " | ".join(parts)
                            log_d(f"Characteristics extracted from SummaryInformationData: {len(parts)} fields")
                except Exception as exc:
                    log_w(f"SummaryInformationData characteristics extraction failed: {exc}")
            
            # Fallback to CLASSIFIED_MAIN_INFOS if SummaryInformationData didn't work
            if not result.get("characteristics") and classified_main_infos:
                try:
                    veh = (((classified_main_infos.get("data") or {}).get("vehicle")) or {})
                    parts: List[str] = []
                    mapping = [
                        ("Boîte de vitesse", ["gearbox"]),
                        ("Énergie", ["energy"]),
                        ("Kilométrage", ["mileage"]),
                        ("Année", ["year"]),
                        ("Mise en circulation", ["firstTrafficDate"]),
                        ("Nombre de propriétaires", ["nbOfOwners"]),
                        ("Couleur", ["externalColor"]),
                        ("Nombre de portes", ["nbOfDoors"]),
                        ("Nombre de places", ["seatingCapacity"]),
                        ("Puissance fiscale", ["fiscalHorsePower"]),
                        ("Puissance DIN", ["powerDin"]),
                        ("Norme euro", ["critair","standardMet"]),
                        ("Crit'Air", ["critair","critairLevel"]),
                        ("Consommation", ["consumption","consumption120"]),
                        ("Emission de CO2", ["co2","combined"]),
                        ("Marque", ["make"]),
                        ("Modèle", ["model"]),
                        ("Version", ["version"]),
                        ("Type de carrosserie", ["bodyType"]),
                        ("Cylindrée", ["displacement"]),
                        ("Carburant", ["fuelType"]),
                        ("Transmission", ["transmission"]),
                        ("Traction", ["driveType"]),
                        ("Première main", ["firstHand"]),
                        ("Contrôle technique", ["technicalInspection"]),
                        ("Garantie", ["warranty"]),
                        ("Historique", ["history"]),
                        ("Positionnement", ["positioning"]),
                    ]
                    for label, path in mapping:
                        val = gv(veh, path)
                        if val is not None:
                            parts.append(f"{label}: {val}")
                    if parts:
                        result["characteristics"] = " | ".join(parts)
                        log_d(f"Characteristics extracted from CLASSIFIED_MAIN_INFOS: {len(parts)} fields")
                except Exception as exc:
                    log_w(f"CLASSIFIED_MAIN_INFOS characteristics extraction failed: {exc}")
                    
        except Exception as exc:
            log_w(f"Characteristics extraction failed: {exc}")

        # Fallback: Try to extract characteristics from the main ad data if CLASSIFIED_MAIN_INFOS failed
        if not result.get("characteristics"):
            try:
                vehicle = ad.get("vehicle", {}) or {}
                parts: List[str] = []
                
                # Basic vehicle characteristics
                for key, label in [
                    ("make", "Marque"),
                    ("model", "Modèle"), 
                    ("version", "Version"),
                    ("year", "Année"),
                    ("mileage", "Kilométrage"),
                    ("gearbox", "Boîte de vitesse"),
                    ("energy", "Énergie"),
                    ("externalColor", "Couleur"),
                    ("nbOfDoors", "Nombre de portes"),
                    ("seatingCapacity", "Nombre de places"),
                    ("fiscalHorsePower", "Puissance fiscale"),
                    ("powerDin", "Puissance DIN"),
                    ("firstTrafficDate", "Mise en circulation"),
                    ("nbOfOwners", "Nombre de propriétaires"),
                ]:
                    val = vehicle.get(key)
                    if val is not None and str(val).strip():
                        parts.append(f"{label}: {val}")
                
                # Nested characteristics
                if isinstance(vehicle.get("critair"), dict):
                    critair = vehicle["critair"]
                    if critair.get("standardMet"):
                        parts.append(f"Norme euro: {critair['standardMet']}")
                    if critair.get("critairLevel"):
                        parts.append(f"Crit'Air: {critair['critairLevel']}")
                
                if isinstance(vehicle.get("consumption"), dict):
                    consumption = vehicle["consumption"]
                    if consumption.get("consumption120"):
                        parts.append(f"Consommation: {consumption['consumption120']}")
                
                if isinstance(vehicle.get("co2"), dict):
                    co2 = vehicle["co2"]
                    if co2.get("combined"):
                        parts.append(f"Emission de CO2: {co2['combined']}")
                
                if parts:
                    result["characteristics"] = " | ".join(parts)
            except Exception:
                pass

        # Phone number: read from JSON only (Base64 in publicationOptions.DI_VN), no clicking
        if not result.get("phone"): # Only try if not already extracted from summary_info or CLASSIFIED_MORE_INFOS
            try:
                pub = ad.get("publicationOptions") or {}
                di_vn = pub.get("DI_VN")
                if isinstance(di_vn, str) and di_vn.strip():
                    s = di_vn.strip()
                    pad = (-len(s)) % 4
                    if pad:
                        s += "=" * pad
                    try:
                        decoded = base64.b64decode(s, validate=False).decode("utf-8", "ignore").strip()
                        if decoded:
                            result["phone"] = re.sub(r"\s+", "", decoded)
                            log_d(f"Phone extracted from publicationOptions.DI_VN: {result['phone']}")
                    except Exception:
                        pass
            except Exception:
                pass

        # Additional fallback: Try to extract phone from __APOLLO_STATE__ if available
        if not result.get("phone"):
            try:
                # Look for __APOLLO_STATE__ in the HTML content
                apollo_match = re.search(r'window\.__APOLLO_STATE__\s*=\s*(\{[\s\S]*?\});', page_content)
                if apollo_match:
                    apollo_data = json.loads(apollo_match.group(1))
                    log_d("Found __APOLLO_STATE__ data, searching for phone numbers...")
                    
                    # Search for Ad:{id} -> publicationOptions -> DI_VN pattern
                    def find_phone_in_apollo_state(obj, path=""):
                        if isinstance(obj, dict):
                            for key, value in obj.items():
                                current_path = f"{path}.{key}" if path else key
                                
                                # Check if this is an Ad object with publicationOptions
                                if key.startswith("Ad:") and isinstance(value, dict):
                                    pub_options = value.get("publicationOptions", {})
                                    di_vn = pub_options.get("DI_VN")
                                    if isinstance(di_vn, str) and di_vn.strip():
                                        try:
                                            s = di_vn.strip()
                                            pad = (-len(s)) % 4
                                            if pad:
                                                s += "=" * pad
                                            decoded = base64.b64decode(s, validate=False).decode("utf-8", "ignore").strip()
                                            if decoded:
                                                phone = re.sub(r"\s+", "", decoded)
                                                log_d(f"Phone extracted from __APOLLO_STATE__ {current_path}: {phone}")
                                                return phone
                                        except Exception as e:
                                            log_d(f"Failed to decode phone from __APOLLO_STATE__ {current_path}: {e}")
                                
                                # Recursively search nested objects
                                result = find_phone_in_apollo_state(value, current_path)
                                if result:
                                    return result
                        elif isinstance(obj, list):
                            for i, item in enumerate(obj):
                                result = find_phone_in_apollo_state(item, f"{path}[{i}]")
                                if result:
                                    return result
                        return None
                    
                    phone = find_phone_in_apollo_state(apollo_data)
                    if phone:
                        result["phone"] = phone
            except Exception as e:
                log_d(f"Failed to extract phone from __APOLLO_STATE__: {e}")

        # Features (if present under ad)
        try:
            strengths = ad.get("strengths")
            feats: List[str] = []
            if isinstance(strengths, list):
                for s in strengths:
                    if not isinstance(s, dict):
                        continue
                    lab = s.get("label"); val = s.get("value")
                    if isinstance(lab, str) and lab.strip():
                        if isinstance(val, str) and val.strip():
                            feats.append(f"{lab.strip()}: {val.strip()}")
                        else:
                            feats.append(lab.strip())
            if feats:
                result["features"] = " | ".join(feats)
        except Exception:
            pass

        # Guarantees/Insurance intentionally omitted

    except Exception:
        return result

    return result

def extract_from_ld_json(html: str) -> Dict[str, Optional[Union[str, int]]]:
    out: Dict[str, Optional[Union[str, int]]] = {
        "title": None,
        "price_eur": None,
        "mileage_km": None,
        "technical_sheet_url": None,
        "warranty": None,
        "equipment_options": None,
        "phone": None,
        "guarantees_insurance": None,
    }
    try:
        soup = BeautifulSoup(html, "html.parser")
        scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
        blocks: List[Dict[str, Any]] = []
        for s in scripts:
            raw = (s.string or s.text or "").strip()
            if not raw:
                continue
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    blocks.append(data)
                elif isinstance(data, list):
                    for it in data:
                        if isinstance(it, dict):
                            blocks.append(it)
            except Exception:
                continue
        best = None
        for b in blocks:
            t = (b.get("@type") or b.get("type") or "")
            t_l = t.lower() if isinstance(t, str) else ""
            if any(x in t_l for x in ["vehicle", "car", "product", "offer"]):
                best = b
                break
        if not best and blocks:
            best = blocks[0]
        if not best:
            return out
        name = best.get("name") or best.get("headline") or best.get("model")
        if isinstance(name, str) and name.strip():
            out["title"] = name.strip()
        offers = best.get("offers")
        def _price_from(v: Any) -> Optional[int]:
            if isinstance(v, (int, float)):
                return int(v)
            if isinstance(v, str):
                d = re.sub(r"[^\d]", "", v)
                return int(d) if d.isdigit() else None
            if isinstance(v, dict):
                return _price_from(v.get("price") or v.get("priceSpecification", {}).get("price"))
            return None
        if isinstance(offers, dict):
            p = _price_from(offers)
            if p is not None:
                out["price_eur"] = p
        elif isinstance(offers, list):
            for o in offers:
                p = _price_from(o)
                if p is not None:
                    out["price_eur"] = p
                    break
        mileage = best.get("mileageFromOdometer") or best.get("mileage")
        if isinstance(mileage, dict):
            val = mileage.get("value") or mileage.get("amount")
            if isinstance(val, (int, float)):
                out["mileage_km"] = int(val)
            elif isinstance(val, str):
                d = re.sub(r"[^\d]", "", val)
                if d.isdigit():
                    out["mileage_km"] = int(d)
        elif isinstance(mileage, (int, float)):
            out["mileage_km"] = int(mileage)
        elif isinstance(mileage, str):
            d = re.sub(r"[^\d]", "", mileage)
            if d.isdigit():
                out["mileage_km"] = int(d)
        warr = best.get("warranty") or best.get("warrantyPromise")
        if isinstance(warr, str) and warr.strip():
            out["warranty"] = warr.strip()
        feats: List[str] = []
        for key in ["featureList", "features", "equipment", "options"]:
            v = best.get(key)
            if isinstance(v, list):
                for it in v:
                    if isinstance(it, str) and it.strip():
                        feats.append(it.strip())
                    elif isinstance(it, dict):
                        lab = it.get("name") or it.get("label") or it.get("title")
                        if isinstance(lab, str) and lab.strip():
                            feats.append(lab.strip())
        if feats:
            seen: set[str] = set(); uniq: List[str] = []
            for x in feats:
                if x not in seen:
                    seen.add(x); uniq.append(x)
            out["equipment_options"] = ", ".join(uniq)
        tsu = best.get("url")
        if isinstance(tsu, str) and "fiche" in tsu.lower():
            out["technical_sheet_url"] = tsu
    except Exception:
        return out
    return out

def extract_from_dom_html(html: str) -> Dict[str, Optional[Union[str, int]]]:
    out: Dict[str, Optional[Union[str, int]]] = {
        "title": None,
        "price_eur": None,
        "mileage_km": None,
        "technical_sheet_url": None,
        "warranty": None,
        "equipment_options": None,
        "phone": None,
        "guarantees_insurance": None,
    }
    try:
        soup = BeautifulSoup(html, "html.parser")
        # Title
        h1 = soup.find(["h1"]) or soup.select_one("[data-testid*='title'], [class*='title'] h1, [class*='title']")
        if h1 and h1.get_text(strip=True):
            out["title"] = h1.get_text(strip=True)
        # Price
        price_el = None
        for sel in ["[class*='price']", "[data-testid*='price']"]:
            price_el = soup.select_one(sel)
            if price_el:
                break
        if not price_el:
            price_el = soup.find(string=re.compile(r"€"))
        if price_el:
            txt = price_el.get_text(strip=True) if hasattr(price_el, 'get_text') else str(price_el)
            d = re.sub(r"[^\d]", "", txt)
            if d.isdigit():
                out["price_eur"] = int(d)
        # Mileage via label
        for label in ["Kilométrage", "Kilometrage", "KM", "km"]:
            dt = soup.find("dt", string=lambda s: isinstance(s, str) and label in s)
            if dt:
                dd = dt.find_next("dd")
                if dd and dd.get_text(strip=True):
                    d = re.sub(r"[^\d]", "", dd.get_text(strip=True))
                    if d.isdigit():
                        out["mileage_km"] = int(d)
                        break
        # Warranty via label
        for label in ["Garantie", "garantie", "Warranty"]:
            dt = soup.find("dt", string=lambda s: isinstance(s, str) and label in s)
            if dt:
                dd = dt.find_next("dd")
                if dd and dd.get_text(strip=True):
                    out["warranty"] = dd.get_text(strip=True)
                    break
        # Equipment & options
        eq_labels = ["Équipements", "Equipements", "Options", "Équipement", "Equipement"]
        section = None
        for head in eq_labels:
            section = soup.find(["h2", "h3", "h4"], string=lambda s: isinstance(s, str) and head in s)
            if section:
                break
        if section:
            container = section.find_parent(["section", "div"]) or section
            items = [li.get_text(strip=True) for li in container.find_all("li") if li.get_text(strip=True)]
            if items:
                seen: set[str] = set(); uniq: List[str] = []
                for it in items:
                    if it not in seen:
                        seen.add(it); uniq.append(it)
                out["equipment_options"] = ", ".join(uniq)
        # Technical sheet
        link = soup.select_one("a[href*='fiche-technique'], a[href*='fiche_technique']")
        if link and link.get("href"):
            out["technical_sheet_url"] = link.get("href")
        # Guarantees & insurance (reuse warranty)
        out["guarantees_insurance"] = out.get("warranty")
    except Exception:
        return out
    return out

def merge_records_preferring(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(a)
    for k, v in (b or {}).items():
        if out.get(k) in (None, "", 0) and v not in (None, "", 0):
            out[k] = v
    return out

def normalize_fr_phone(raw_number: str) -> Optional[str]:
    try:
        d = re.sub(r"\D", "", raw_number or "")
        if not d:
            return None
        if d.startswith("0033"):
            d = d[2:]
        if d.startswith("33") and len(d) >= 11:
            last9 = d[-9:]
            return "0" + last9
        if d.startswith("0") and len(d) >= 10:
            return d[:10]
        return None
    except Exception:
        return None

def extract_from_dom_page(page) -> Dict[str, Optional[Union[str, int]]]:
    out: Dict[str, Optional[Union[str, int]]] = {
        "title": None,
        "price_eur": None,
        "mileage_km": None,
        "technical_sheet_url": None,
        "warranty": None,
        "equipment_options": None,
        "phone": None,
        "guarantees_insurance": None,
        "features": None,
        "seller_comment": None,
        "agency_name": None,
    }
    def safe_text(sel: str) -> Optional[str]:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                t = (loc.inner_text(timeout=2000) or "").strip()
                return t or None
        except Exception:
            return None
        return None
    def safe_attr(sel: str, attr: str) -> Optional[str]:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                v = loc.get_attribute(attr, timeout=2000)
                return v.strip() if v else None
        except Exception:
            return None
        return None
    # Title
    out["title"] = safe_text("h1") or safe_text("aside h2") or safe_text("[data-testid*='title'], [class*='title'] h1, [class*='title']")
    # Price
    price_txt = safe_text("[class*='price']") or safe_text("[data-testid*='price']") or safe_text("xpath=(//*[contains(text(),'€')])[1]")
    if price_txt:
        digits = re.sub(r"[^\d]", "", price_txt)
        if digits.isdigit():
            out["price_eur"] = int(digits)
    # Mileage by label (Kilométrage)
    try:
        for label in ["Kilométrage", "Kilometrage", "KM", "km"]:
            loc = page.locator(f"xpath=//dt[contains(normalize-space(.), '{label}')]/following-sibling::dd[1]").first
            if loc.count() > 0:
                txt = (loc.inner_text(timeout=1500) or "").strip()
                d = re.sub(r"[^\d]", "", txt)
                if d.isdigit():
                    out["mileage_km"] = int(d)
                    break
    except Exception:
        pass
    # Technical sheet
    out["technical_sheet_url"] = (
        safe_attr("a:has-text('Fiche technique')", "href")
        or safe_attr("a:has-text('Fiche')", "href")
        or safe_attr("a[href*='fiche-technique']", "href")
        or safe_attr("a[href*='fiche_technique']", "href")
    )
    # Seller comment
    try:
        sec = page.locator("xpath=(//*[self::h2 or self::h3][contains(normalize-space(.), 'Commentaire du vendeur')])[1]/ancestor::*[self::section or self::div][1]").first
        if sec.count() > 0:
            txt = (sec.inner_text(timeout=2000) or "").strip()
            # Trim heading
            out["seller_comment"] = re.sub(r"^\s*Commentaire du vendeur\s*", "", txt, flags=re.IGNORECASE).strip()
    except Exception:
        pass
    # Equipment & options
    try:
        head = page.locator("xpath=(//*[self::h2 or self::h3][contains(normalize-space(.), 'Équipements') or contains(normalize-space(.), 'Equipements') or contains(normalize-space(.), 'Options')])[1]").first
        if head.count() > 0:
            container = head.locator("xpath=ancestor::*[self::section or self::div][1]").first
            lis = container.locator("xpath=.//li").all()
            items: List[str] = []
            for li in lis:
                try:
                    t = (li.inner_text(timeout=1000) or "").strip()
                    if t:
                        items.append(re.sub(r"\s+", " ", t))
                except Exception:
                    continue
            if items:
                seen: set[str] = set(); uniq: List[str] = []
                for it in items:
                    if it not in seen:
                        seen.add(it); uniq.append(it)
                out["equipment_options"] = ", ".join(uniq)
    except Exception:
        pass
    # Warranty from label
    try:
        loc = page.locator("xpath=//dt[contains(., 'Garantie')]/following-sibling::dd[1]").first
        if loc.count() > 0:
            w = (loc.inner_text(timeout=1500) or "").strip()
            if w:
                out["warranty"] = w
                out["guarantees_insurance"] = w
    except Exception:
        pass
    # Agency name under "Automobile agency"
    try:
        sec = page.locator("xpath=(//*[self::h2 or self::h3][contains(normalize-space(.), 'Automobile agency') or contains(normalize-space(.), 'Agence')])[1]/ancestor::*[self::section or self::div][1]").first
        if sec.count() > 0:
            # Prefer a seller link/text, exclude buttons like "Voir ..."
            selectors = [
                "xpath=.//a[not(contains(normalize-space(.),'Voir')) and string-length(normalize-space(.))>3]",
                "xpath=.//strong[string-length(normalize-space(.))>3]",
                "xpath=.//*[contains(@class,'Seller') or contains(@class,'title') or contains(@class,'name')][1]",
            ]
            for sel in selectors:
                try:
                    cand = sec.locator(sel).first
                    if cand.count() > 0:
                        txt = (cand.inner_text(timeout=1500) or "").strip()
                        if txt and not re.search(r"Automobile|Agence|Voir|carte|annonces du pro", txt, re.IGNORECASE):
                            out["agency_name"] = re.sub(r"\s+", " ", txt)
                            break
                except Exception:
                    continue
            if not out.get("agency_name"):
                # Fallback: locate the "Voir les annonces du pro" button and walk container for a non-button title
                try:
                    btn = sec.locator("xpath=.//*[contains(normalize-space(.), 'annonces du pro')]").first
                    card = btn.locator("xpath=ancestor::*[self::section or self::div][1]").first if btn.count() > 0 else sec
                    cand = card.locator("xpath=.//a[not(contains(normalize-space(.),'Voir')) and string-length(normalize-space(.))>3] | .//strong[string-length(normalize-space(.))>3]").first
                    if cand.count() > 0:
                        txt = (cand.inner_text(timeout=1500) or "").strip()
                        if txt and not re.search(r"Voir|annonces du pro|Automobile|Agence", txt, re.IGNORECASE):
                            out["agency_name"] = re.sub(r"\s+", " ", txt)
                except Exception:
                    pass
    except Exception:
        pass
    # Phone: click reveal, then prefer the exact visible number near the button
    try:
        for label in ["N° téléphone", "Phone number", "Numéro", "Voir le numéro", "Afficher le numéro", "Téléphone"]:
            btn = page.locator(f"xpath=//*[self::button or self::a][contains(normalize-space(.), '{label}')] ").first
            if btn.count() > 0:
                try:
                    btn.scroll_into_view_if_needed(timeout=1500)
                    polite_sleep(0.3, 0.7)
                    btn.click(timeout=2000)
                    polite_sleep(0.6, 1.2)
                except Exception:
                    pass
                break
        # 1) Prefer nearby visible text around the button
        if 'btn' in locals() and btn and btn.count() > 0:
            try:
                area = btn.evaluate("el => (el.closest('section,div,aside')?.innerText || el.parentElement?.innerText || el.innerText || '')") or ""
            except Exception:
                area = ""
            # find the longest run of digits/spaces and collapse spaces only
            numerics = re.findall(r"[\d\s]{10,}", area)
            numerics = sorted(numerics, key=lambda s: len(re.sub(r"\s+", "", s)), reverse=True)
            for g in numerics or []:
                digits_no_space = re.sub(r"\s+", "", g)
                if len(digits_no_space) >= 10:
                    out["phone"] = digits_no_space
                    break
        # 2) tel: link as fallback (remove spaces only)
        if not out["phone"]:
            try:
                page.wait_for_selector("a[href^='tel:']", timeout=2000)
            except Exception:
                pass
            tel = safe_attr("a[href^='tel:']", "href")
            if tel and tel.lower().startswith("tel:"):
                out["phone"] = re.sub(r"\s+", "", tel[4:])
        # Also check data-phone attributes in the reveal button (sometimes base64 or plaintext)
        if not out["phone"] and btn and btn.count() > 0:
            try:
                dp = btn.get_attribute("data-phone")
                if dp:
                    s = dp.strip()
                    pad = (-len(s)) % 4
                    if pad:
                        s += "=" * pad
                    try:
                        decoded = base64.b64decode(s, validate=False).decode("utf-8", "ignore").strip()
                    except Exception:
                        decoded = s
                    out["phone"] = re.sub(r"\s+", "", decoded)
            except Exception:
                pass
        if not out["phone"]:
            body = safe_text("body") or ""
            m = re.findall(r"[\d\s]{10,}", body)
            for g in m or []:
                digits_no_space = re.sub(r"\s+", "", g)
                if len(digits_no_space) >= 10:
                    out["phone"] = digits_no_space; break
    except Exception:
        pass
    # Feature chips (Historique, Kilométrage, Consommation, Positionnement)
    try:
        # Prefer strengths section container to avoid picking entire page text
        strengths = page.locator("#strengths").first
        chips: List[str] = []
        srcs = [strengths] if strengths.count() > 0 else [page.locator("xpath=(//*[self::section or self::div][contains(@id,'strength')])[1]").first]
        for src in srcs:
            try:
                lis = src.locator("xpath=.//li|.//*[@role='listitem']").all()
                for li in lis:
                    try:
                        txt = (li.inner_text(timeout=800) or "").strip()
                        if txt:
                            chips.append(re.sub(r"\s+", " ", txt))
                    except Exception:
                        continue
            except Exception:
                continue
        if chips:
            seen: set[str] = set(); uniq: List[str] = []
            for c in chips:
                if c not in seen and len(c) < 80:
                    seen.add(c); uniq.append(c)
            if uniq:
                out["features"] = "\n".join(uniq)
    except Exception:
        pass
    # Caractéristiques (dt/dd pairs), with multiple fallbacks
    try:
        head = page.locator("xpath=(//*[self::h2 or self::h3][contains(normalize-space(.), 'Caractéristiques') or contains(normalize-space(.), 'Caracteristiques')])[1]").first
        container = None
        if head.count() > 0:
            container = head.locator("xpath=ancestor::*[self::section or self::div][1]").first
        if not container or container.count() == 0:
            container = page.locator("xpath=(//*[contains(@id,'caracter') or contains(@id,'caract') or contains(@id,'character') or contains(@data-testid,'caract')])[1]").first
        if container and container.count() > 0:
            lines: List[str] = []
            # Preferred: dt/dd pairs
            dts = container.locator("xpath=.//dt").all()
            if dts:
                for dt in dts:
                    try:
                        label = (dt.inner_text(timeout=800) or "").strip()
                        dd = dt.locator("xpath=following-sibling::dd[1]").first
                        value = (dd.inner_text(timeout=800) or "").strip() if dd.count() > 0 else ""
                        if label and value:
                            lines.append(f"{label}: {value}")
                    except Exception:
                        continue
            # Fallback: known labels in grid rows
            if not lines:
                known = [
                    "Année","Kilométrage","Boîte de vitesse","Énergie","Energie","Nombre de portes",
                    "Puissance fiscale","Puissance DIN","Consommation"
                ]
                for lab in known:
                    try:
                        node = container.locator(f"xpath=.//*[contains(normalize-space(.), '{lab}')]").first
                        if node.count() == 0:
                            continue
                        row = node.locator("xpath=ancestor::*[self::div or self::li or self::tr][1]").first
                        if row.count() == 0:
                            continue
                        txt = (row.inner_text(timeout=800) or "").strip()
                        if not txt:
                            continue
                        # remove label once
                        val = re.sub(lab, "", txt, flags=re.IGNORECASE).strip()
                        if val and len(val) <= 40:
                            lines.append(f"{lab}: {val}")
                    except Exception:
                        continue
            if lines:
                out["characteristics"] = "\n".join(lines)
    except Exception:
        pass
    return out

def collect_ad_urls_with_source_pages(page) -> List[Tuple[str, int]]:
    """Return list of (ad_url, listing_page_num) for click-through navigation."""
    found: List[Tuple[str, int]] = []
    seen: set[str] = set()
    
    # Load already processed URLs to avoid collecting them again
    processed_urls = set()
    excel_path = "lacentrale_listings.xlsx"
    json_path = "lacentrale_listings.json"
    
    # Check Excel file
    if os.path.exists(excel_path):
        try:
            existing_df = pd.read_excel(excel_path)
            if 'ad_url' in existing_df.columns:
                processed_urls.update(existing_df['ad_url'].tolist())
        except Exception:
            pass
    
    # Check JSON file
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
            if isinstance(existing_data, list):
                processed_urls.update(record.get('ad_url', '') for record in existing_data)
        except Exception:
            pass
    
    if processed_urls:
        log_i(f"Found {len(processed_urls)} already processed URLs, will skip them")
    
    page_num = 1
    consecutive_empty_pages = 0
    max_consecutive_empty_pages = 5  # Stop after 5 consecutive pages with no new ads
    
    while page_num <= MAX_PAGES and len(found) < MAX_ADS and consecutive_empty_pages < max_consecutive_empty_pages:
        url = f"{LISTING_URL}?page={page_num}"
        page.goto(url, wait_until="domcontentloaded", timeout=REQUEST_TIMEOUT_MS)
        polite_sleep()
        html = page.content()
        if is_block_page(html):
            save_debug_html(f"listing_page_{page_num}_block.html", html)
            log_w(f"Block on listing page {page_num}. Solve in Chrome, then press Enter.")
            try:
                input()
            except Exception:
                pass
            page.reload(wait_until="domcontentloaded", timeout=REQUEST_TIMEOUT_MS)
            polite_sleep()
            html = page.content()
            if is_block_page(html):
                log_w("Still blocked after retry; stopping.")
                break

        page_new: List[str] = []

        # Prefer JSON
        next_data = parse_next_data_from_html(html)
        if next_data:
            for node in walk_json(next_data):
                if isinstance(node, str):
                    u = to_abs(node)
                    if is_ad_url(u) and u not in seen and u not in processed_urls:
                        seen.add(u); page_new.append(u)
                elif isinstance(node, dict):
                    for k in ("href", "url", "canonical", "link"):
                        v = node.get(k)
                        if isinstance(v, str):
                            u = to_abs(v)
                            if is_ad_url(u) and u not in seen and u not in processed_urls:
                                seen.add(u); page_new.append(u)

        # Fallback: anchors on page
        if not page_new:
            hrefs = page.eval_on_selector_all('a[href*="auto-occasion-annonce-"]', 'els => els.map(e => e.getAttribute("href"))')
            for h in hrefs or []:
                u = to_abs(h)
                if is_ad_url(u) and u not in seen and u not in processed_urls:
                    seen.add(u); page_new.append(u)

        if not page_new:
            consecutive_empty_pages += 1
            log_i(f"Page {page_num}: No new ad URLs found on this page (consecutive empty: {consecutive_empty_pages})")
            # Continue to next page instead of stopping
            page_num += 1
            continue
        else:
            consecutive_empty_pages = 0  # Reset counter when we find new ads

        for u in page_new:
            found.append((u, page_num))
            if len(found) >= MAX_ADS:
                break

        log_i(f"Page {page_num}: +{len(page_new)} (total={len(found)})")
        if len(found) >= MAX_ADS:
            break
        page_num += 1

    # Log why we stopped searching
    if consecutive_empty_pages >= max_consecutive_empty_pages:
        log_i(f"Stopped searching after {consecutive_empty_pages} consecutive pages with no new ads")
    elif len(found) >= MAX_ADS:
        log_i(f"Stopped searching after reaching maximum ads limit ({MAX_ADS})")
    elif page_num > MAX_PAGES:
        log_i(f"Stopped searching after reaching maximum pages limit ({MAX_PAGES})")
    
    sample = [u for (u, _) in found[:10]]
    if sample:
        log_i(f"Sample ad URLs: {sample}")
    return found[:MAX_ADS]

def click_through_to_ad(page, ad_url: str, listing_page_num: int) -> bool:
    """Navigate to the listing page, scroll to the exact ad anchor, and click it."""
    listing_url = f"{LISTING_URL}?page={listing_page_num}"
    page.goto(listing_url, wait_until="domcontentloaded", timeout=REQUEST_TIMEOUT_MS)
    polite_sleep(0.8, 1.6)
    human_scroll(page, times=random.randint(3, 6))

    # Try exact href match first (absolute)
    selector_abs = f'a[href="{ad_url}"]'
    selector_rel = f'a[href="{ad_url.replace(BASE_URL, "")}"]'

    # Try to make the element visible and click
    for sel in [selector_abs, selector_rel, 'a[href*="auto-occasion-annonce-"]']:
        try:
            locator = page.locator(sel).first
            locator.scroll_into_view_if_needed(timeout=3000)
            polite_sleep(CLICK_WAIT_MIN, CLICK_WAIT_MAX)
            human_wiggle(page)
            locator.click(timeout=5000)
            page.wait_for_load_state("domcontentloaded", timeout=REQUEST_TIMEOUT_MS)
            polite_sleep(1.0, 2.0)
            return True
        except Exception:
            continue
    return False

def scrape_ads_to_files() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(CDP_URL)
        if not browser.contexts:
            raise RuntimeError("No contexts found in Chrome. Start Chrome with --remote-debugging-port=9222 and open the site.")
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        print("\n[info] In Chrome: ensure homepage and listing open normally (no block). Press Enter to continue.")
        try:
            input()
        except Exception:
            pass

        log_i("Collecting ad URLs ...")
        ad_sources = collect_ad_urls_with_source_pages(page)
        ad_urls = [u for (u, _) in ad_sources]
        log_i(f"Total ad URLs collected: {len(ad_urls)}")

        rows: List[Dict[str, Any]] = []
        total = len(ad_sources)
        processed = 0

        while processed < total:
            batch = ad_sources[processed: processed + BATCH_SIZE]
            log_i(f"Processing batch {processed+1}-{processed+len(batch)} of {total}")

            for idx_in_batch, (ad, src_page) in enumerate(batch, start=1):
                i = processed + idx_in_batch
                log_i(f"[{i}/{total}] Clicking from listing page {src_page} -> {ad}")

                # Click through from its listing page (preserve Referer + event chain)
                ok = click_through_to_ad(page, ad, src_page)
                if not ok:
                    log_w(f"Could not click ad on listing page {src_page}, fallback direct goto.")
                    try:
                        page.goto(ad, wait_until="domcontentloaded", timeout=REQUEST_TIMEOUT_MS)
                    except Exception:
                        log_w("Direct goto failed; skipping.")
                        continue

                polite_sleep(1.2, 2.5)
                human_scroll(page, times=random.randint(2, 4))

                html = page.content()
                if is_block_page(html):
                    save_debug_html(f"ad_{i}_block.html", html)
                    log_w(f"Block on ad {i}. Solve in Chrome, then press Enter.")
                    try:
                        input()
                    except Exception:
                        pass
                    try:
                        page.reload(wait_until="domcontentloaded", timeout=REQUEST_TIMEOUT_MS)
                    except Exception:
                        pass
                    polite_sleep(1.2, 2.0)
                    html = page.content()
                    if is_block_page(html):
                        log_w("Still blocked; skipping this ad.")
                        continue

                # Try JSON extraction first
                record = extract_ad_details(html, ad)
                
                # If no phone number found in JSON, try to reveal it by clicking the button
                if not record.get("phone"):
                    log_d(f"No phone found in JSON for {ad}, trying to reveal phone number...")
                    revealed_phone = _reveal_phone_number(page)
                    if revealed_phone:
                        record["phone"] = revealed_phone
                        log_d(f"Phone number revealed: {revealed_phone}")
                
                # If JSON extraction failed, try DOM extraction as fallback
                if not record.get("title") and not record.get("price_eur"):
                    log_d(f"JSON extraction failed for {ad}, trying DOM extraction")
                    dom_record = extract_from_dom_page(page)
                    if dom_record.get("title") or dom_record.get("price_eur"):
                        record = dom_record
                        record["ad_url"] = ad
                        log_d(f"DOM extraction succeeded: title={record.get('title')}, price={record.get('price_eur')}")
                
                # Clean up noisy 'features' content lines and strip any JS blob remnants
                if record.get("features"):
                    lines = [re.sub(r"\s+", " ", ln).strip() for ln in str(record["features"]).splitlines()]
                    keep = []
                    for ln in lines:
                        if not ln:
                            continue
                        if ln.startswith("var ") or ln.endswith("};") or ln.endswith("}}"):  # strip JS snippet noise
                            continue
                        keep.append(ln)
                    record["features"] = "\n".join(keep) if keep else None
                    
                if not record.get("title") and not record.get("price_eur"):
                    save_debug_html(f"ad_{i}_no_data.html", html)
                    log_w(f"Ad {i}: no essential data found; skipping.")
                    continue
                # Ensure guarantees_insurance mirrors warranty if still empty
                record["ad_url"] = ad
                rows.append(record)

                # Light pacing between ads
                polite_sleep()

                # Occasionally go back through history to mimic user behavior
                if random.random() < 0.35:
                    try:
                        page.go_back(wait_until="domcontentloaded", timeout=REQUEST_TIMEOUT_MS)
                        polite_sleep(0.8, 1.5)
                    except Exception:
                        pass

            processed += len(batch)

            # Cooldown between batches to reduce triggers
            if processed < total:
                log_i(f"Batch complete. Suggested cooldown ~{COOLDOWN_SECONDS}s. Press Enter to continue immediately or wait.")
                try:
                    input()
                except Exception:
                    pass

        if not rows:
            log_w("No ads extracted. Excel will not be created.")
            return

        # Save to both Excel and JSON with proper field ordering
        excel_path = "lacentrale_listings.xlsx"
        json_path = "lacentrale_listings.json"
        
        # Define the exact field order as requested
        field_order = [
            "title", "price_eur", "agency_name", "phone", "address", 
            "mileage_km", "equipment_options", "characteristics", 
            "features", "seller_comment", "ad_url"
        ]
        
        # Load existing data if files exist
        existing_excel_data = []
        existing_json_data = []
        processed_urls = set()
        
        # Load existing Excel data
        if os.path.exists(excel_path):
            try:
                existing_df = pd.read_excel(excel_path)
                existing_excel_data = existing_df.to_dict('records')
                processed_urls = set(existing_df['ad_url'].tolist() if 'ad_url' in existing_df.columns else [])
                log_i(f"Found existing Excel file with {len(existing_excel_data)} records")
            except Exception as e:
                log_w(f"Could not read existing Excel file: {e}")
        
        # Load existing JSON data
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    existing_json_data = json.load(f)
                if isinstance(existing_json_data, list):
                    processed_urls.update(record.get('ad_url', '') for record in existing_json_data)
                log_i(f"Found existing JSON file with {len(existing_json_data)} records")
            except Exception as e:
                log_w(f"Could not read existing JSON file: {e}")
        
        # Filter out already processed ads
        new_rows = []
        for row in rows:
            if row.get('ad_url') not in processed_urls:
                new_rows.append(row)
            else:
                log_d(f"Skipping already processed ad: {row.get('ad_url')}")
        
        if not new_rows:
            log_i("No new ads to process. All ads have already been scraped.")
            return
        
        log_i(f"Processing {len(new_rows)} new ads (skipped {len(rows) - len(new_rows)} already processed)")
        
        # Combine existing and new data
        all_excel_data = existing_excel_data + new_rows
        all_json_data = existing_json_data + new_rows
        
        # Create DataFrame with proper field ordering
        df = pd.DataFrame(all_excel_data)
        for c in field_order:
            if c not in df.columns:
                df[c] = None
        df = df[field_order]
        
        # Save Excel file
        df.to_excel(excel_path, index=False)
        log_i(f"Saved {len(df)} total rows to {excel_path} ({len(new_rows)} new)")
        
        # Save JSON file
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(all_json_data, f, ensure_ascii=False, indent=2)
        log_i(f"Saved {len(all_json_data)} total records to {json_path} ({len(new_rows)} new)")

if __name__ == "__main__":
    try:
        scrape_ads_to_files()
    except Exception as e:
        print(f"[error] Unhandled: {type(e).__name__}: {e}")
