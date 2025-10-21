#!/usr/bin/env python3

import re
import json
from bs4 import BeautifulSoup

def test_phone_extraction():
    # Read the actual HTML file
    with open('debug_http/ad_1_no_data.html', 'r') as f:
        html = f.read()
    
    print("Testing phone extraction from CLASSIFIED_MORE_INFOS...")
    
    # Find CLASSIFIED_MORE_INFOS script block
    more_infos_script = None
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script"):
        if script.string and "CLASSIFIED_MORE_INFOS" in script.string:
            more_infos_script = script.string
            print("Found CLASSIFIED_MORE_INFOS script block")
            break
    
    if not more_infos_script:
        print("CLASSIFIED_MORE_INFOS script block not found")
        return
    
    # Extract CLASSIFIED_MORE_INFOS data
    m = re.search(r"var\s+CLASSIFIED_MORE_INFOS\s*=\s*(\{[\s\S]*?\})\s*;", more_infos_script)
    if not m:
        print("Could not extract CLASSIFIED_MORE_INFOS data")
        print("Script content preview:", more_infos_script[:200])
        return
    
    try:
        more_infos_data = json.loads(m.group(1))
        print("Successfully parsed CLASSIFIED_MORE_INFOS data")
        
        # Look for phone in showroom contacts
        seller_infos = more_infos_data.get("sellerInfos", {})
        print(f"SellerInfos keys: {list(seller_infos.keys())}")
        
        showroom = seller_infos.get("showroom", {})
        print(f"Showroom keys: {list(showroom.keys())}")
        
        contacts = showroom.get("contacts", [])
        print(f"Contacts: {contacts}")
        
        if isinstance(contacts, list) and contacts:
            for i, contact in enumerate(contacts):
                print(f"Contact {i}: {contact}")
                if isinstance(contact, dict) and contact.get("phone"):
                    phone = contact.get("phone")
                    print(f"Found phone: {phone}")
                    return phone
        
        print("No phone found in contacts")
        
    except Exception as exc:
        print(f"Failed to parse CLASSIFIED_MORE_INFOS: {exc}")

if __name__ == "__main__":
    test_phone_extraction()
