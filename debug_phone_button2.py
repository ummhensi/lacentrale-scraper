#!/usr/bin/env python3

import sys
sys.path.append('.')
from scraper_cdp import is_block_page
from playwright.sync_api import sync_playwright

def debug_phone_button2():
    """Debug phone button selectors with better error handling"""
    
    test_url = "https://www.lacentrale.fr/auto-occasion-annonce-87103270856.html"
    
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page()
        
        try:
            print(f"Navigating to: {test_url}")
            page.goto(test_url)
            
            # Wait for page to load
            page.wait_for_timeout(10000)  # Wait 10 seconds
            
            # Check if we're blocked
            html = page.content()
            if is_block_page(html):
                print("❌ Page is blocked!")
                return
            
            print("✅ Page loaded successfully")
            
            # Get page title
            title = page.title()
            print(f"Page title: {title}")
            
            # Check if we're on the right page
            if "annonce" not in title.lower():
                print("❌ Not on an ad page")
                return
            
            print("\n=== Searching for phone-related elements ===")
            
            # Look for any button with phone-related text
            all_buttons = page.query_selector_all('button')
            print(f"Found {len(all_buttons)} buttons on page")
            
            phone_buttons = []
            for i, button in enumerate(all_buttons):
                try:
                    text = button.inner_text().strip()
                    if text and any(word in text.lower() for word in ['téléphone', 'appeler', 'phone', 'contact']):
                        phone_buttons.append((i, text, button))
                        print(f"Phone-related button {i}: '{text}'")
                except:
                    pass
            
            if not phone_buttons:
                print("No phone-related buttons found")
                
                # Let's check what buttons we do have
                print("\nFirst 10 buttons on page:")
                for i, button in enumerate(all_buttons[:10]):
                    try:
                        text = button.inner_text().strip()
                        if text:
                            print(f"Button {i}: '{text}'")
                    except:
                        pass
            else:
                # Try clicking the first phone button
                print(f"\nTrying to click first phone button: '{phone_buttons[0][1]}'")
                phone_buttons[0][2].click()
                page.wait_for_timeout(2000)
                
                # Look for revealed phone number
                all_spans = page.query_selector_all('span')
                for span in all_spans:
                    try:
                        text = span.inner_text().strip()
                        if text and len(text) >= 8 and any(c.isdigit() for c in text):
                            print(f"Potential phone number: '{text}'")
                    except:
                        pass
                        
        except Exception as e:
            print(f"Error: {e}")
        finally:
            print("Closing browser in 5 seconds...")
            page.wait_for_timeout(5000)
            browser.close()

if __name__ == "__main__":
    debug_phone_button2()
