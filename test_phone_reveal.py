#!/usr/bin/env python3

import sys
sys.path.append('.')
from scraper_cdp import _reveal_phone_number
from playwright.sync_api import sync_playwright

def test_phone_reveal():
    """Test phone number revelation on a real ad page"""
    
    # Test URL - you can change this to any ad URL
    test_url = "https://www.lacentrale.fr/auto-occasion-annonce-87103270856.html"
    
    with sync_playwright() as pw:
        # Launch browser
        browser = pw.chromium.launch(headless=False)  # Set to True for headless mode
        page = browser.new_page()
        
        try:
            print(f"Navigating to: {test_url}")
            page.goto(test_url)
            
            # Wait for page to load
            page.wait_for_timeout(3000)
            
            print("Attempting to reveal phone number...")
            phone = _reveal_phone_number(page)
            
            if phone:
                print(f"✅ Phone number revealed: {phone}")
            else:
                print("❌ No phone number revealed")
                
        except Exception as e:
            print(f"Error: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    test_phone_reveal()
