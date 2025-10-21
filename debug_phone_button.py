#!/usr/bin/env python3

import sys
sys.path.append('.')
from playwright.sync_api import sync_playwright

def debug_phone_button():
    """Debug phone button selectors on a real ad page"""
    
    test_url = "https://www.lacentrale.fr/auto-occasion-annonce-87103270856.html"
    
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page()
        
        try:
            print(f"Navigating to: {test_url}")
            page.goto(test_url)
            
            # Wait for page to load
            page.wait_for_timeout(5000)
            
            print("\n=== Searching for phone-related elements ===")
            
            # Look for various phone button selectors
            selectors_to_try = [
                'button[data-testid="button"][data-page-zone="telephone"][id="summary-contact-phone"]',
                'button[id="summary-contact-phone"]',
                'button[data-page-zone="telephone"]',
                'button[data-testid="button"]',
                'button:has-text("téléphone")',
                'button:has-text("Appeler")',
                'button:has-text("N° téléphone")',
                '#summary-contact-phone',
                '.ContactInformation_phone__qlEra',
                '#contactInfoWrapper button',
                '#summary-information button'
            ]
            
            for selector in selectors_to_try:
                try:
                    element = page.query_selector(selector)
                    if element:
                        text = element.inner_text().strip()
                        print(f"✅ Found: {selector} -> '{text}'")
                    else:
                        print(f"❌ Not found: {selector}")
                except Exception as e:
                    print(f"❌ Error with {selector}: {e}")
            
            print("\n=== All buttons on page ===")
            buttons = page.query_selector_all('button')
            for i, button in enumerate(buttons[:10]):  # Show first 10 buttons
                try:
                    text = button.inner_text().strip()
                    if text and ('téléphone' in text.lower() or 'appeler' in text.lower() or 'phone' in text.lower()):
                        print(f"Button {i}: '{text}'")
                except:
                    pass
                    
            print("\n=== Contact info wrapper ===")
            contact_wrapper = page.query_selector('#contactInfoWrapper')
            if contact_wrapper:
                print("✅ Found #contactInfoWrapper")
                html = contact_wrapper.inner_html()
                print(f"HTML: {html[:500]}...")
            else:
                print("❌ #contactInfoWrapper not found")
                
        except Exception as e:
            print(f"Error: {e}")
        finally:
            input("Press Enter to close browser...")
            browser.close()

if __name__ == "__main__":
    debug_phone_button()
