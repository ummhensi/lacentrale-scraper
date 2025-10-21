#!/usr/bin/env python3

import sys
sys.path.append('.')

from scraper_cdp import extract_ad_details

def test_actual_extraction():
    # Read the actual HTML file
    with open('debug_http/ad_1_no_data.html', 'r') as f:
        html = f.read()
    
    print("Testing actual extract_ad_details function...")
    result = extract_ad_details(html, "test_url")
    
    print("\n=== EXTRACTION RESULT ===")
    for key, value in result.items():
        if value is not None:
            print(f"{key}: {value}")
        else:
            print(f"{key}: None")

if __name__ == "__main__":
    test_actual_extraction()
