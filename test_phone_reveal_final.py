#!/usr/bin/env python3
"""
Test script to verify phone number revelation functionality
"""

import os
import sys
import re
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

def is_block_page(content: str) -> bool:
    """Check if the page is blocked by anti-bot measures"""
    block_indicators = [
        "Access blocked",
        "Cloudflare",
        "DataDome",
        "Please wait while we check your browser",
        "Checking your browser before accessing",
        "Ray ID:",
        "Error 1020",
        "Error 1015",
        "Just a moment",
        "DDoS protection by Cloudflare"
    ]
    content_lower = content.lower()
    return any(indicator.lower() in content_lower for indicator in block_indicators)

def _reveal_phone_number(page) -> str:
    """
    Click the phone button to reveal the phone number and extract it.
    """
    try:
        # Look for the phone button with the specific selector
        phone_button = page.query_selector('button[id="summary-contact-phone"]')
        if not phone_button:
            # Try alternative selectors
            phone_button = page.query_selector('button[data-page-zone="telephone"]')
        if not phone_button:
            phone_button = page.query_selector('button.ContactInformation_phone__qlEra')
        
        if phone_button:
            print("Found phone button, clicking to reveal phone number...")
            phone_button.click()
            
            # Wait a moment for the phone number to appear
            page.wait_for_timeout(2000)
            
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
                            print(f"Phone number revealed: {phone_clean}")
                            return phone_clean
                except Exception as e:
                    print(f"Error checking selector {selector}: {e}")
                    continue
            
            # If no specific selector worked, try to find any span with a phone-like pattern
            try:
                all_spans = page.query_selector_all('span')
                for span in all_spans:
                    text = span.inner_text().strip()
                    if re.search(r'\d{2}\s+\d{2}\s+\d{2}\s+\d{2}', text):
                        phone_clean = re.sub(r'\s+', '', text)
                        print(f"Phone number found in span: {phone_clean}")
                        return phone_clean
            except Exception as e:
                print(f"Error searching all spans: {e}")
        
        print("No phone button found or phone number not revealed")
        return ""
        
    except Exception as e:
        print(f"Error revealing phone number: {e}")
        return ""

def test_phone_reveal():
    """Test phone number revelation on a real ad page"""
    
    # Test URL - using one of the URLs from our debug files
    test_url = "https://www.lacentrale.fr/auto-occasion-annonce-87103270856.html"
    
    print(f"Testing phone revelation on: {test_url}")
    
    with sync_playwright() as pw:
        # Connect to existing Chrome instance
        try:
            browser = pw.chromium.connect_over_cdp("http://localhost:9222")
            print("Connected to existing Chrome instance")
        except Exception as e:
            print(f"Failed to connect to Chrome: {e}")
            print("Please make sure Chrome is running with: --remote-debugging-port=9222")
            return
        
        # Get the default context
        contexts = browser.contexts
        if not contexts:
            print("No browser contexts found")
            return
        
        context = contexts[0]
        page = context.new_page()
        
        try:
            print("Navigating to test URL...")
            page.goto(test_url, wait_until="networkidle", timeout=30000)
            
            # Check if page is blocked
            content = page.content()
            if is_block_page(content):
                print("Page is blocked by anti-bot measures")
                print("Please solve any CAPTCHA or wait for the page to load normally")
                input("Press Enter after solving CAPTCHA...")
                page.reload(wait_until="networkidle", timeout=30000)
                content = page.content()
                if is_block_page(content):
                    print("Page is still blocked after reload")
                    return
            
            print("Page loaded successfully")
            
            # Test phone revelation
            phone = _reveal_phone_number(page)
            if phone:
                print(f"SUCCESS: Phone number revealed: {phone}")
            else:
                print("FAILED: No phone number revealed")
                
                # Debug: Check what's on the page
                print("\nDebugging page content...")
                
                # Check if phone button exists
                phone_button = page.query_selector('button[id="summary-contact-phone"]')
                if phone_button:
                    print("Phone button found")
                    button_text = phone_button.inner_text()
                    print(f"Button text: {button_text}")
                else:
                    print("Phone button NOT found")
                
                # Check for any phone-related elements
                phone_elements = page.query_selector_all('[class*="phone"], [class*="telephone"], [id*="phone"], [id*="telephone"]')
                print(f"Found {len(phone_elements)} phone-related elements")
                for i, elem in enumerate(phone_elements[:5]):  # Show first 5
                    try:
                        tag = elem.evaluate("el => el.tagName")
                        classes = elem.evaluate("el => el.className")
                        text = elem.inner_text()[:50] if elem.inner_text() else ""
                        print(f"  {i+1}. {tag} class='{classes}' text='{text}'")
                    except:
                        pass
                
                # Check for any spans with phone-like patterns
                all_spans = page.query_selector_all('span')
                phone_spans = []
                for span in all_spans:
                    try:
                        text = span.inner_text().strip()
                        if re.search(r'\d{2}\s+\d{2}\s+\d{2}\s+\d{2}', text):
                            phone_spans.append(text)
                    except:
                        pass
                
                if phone_spans:
                    print(f"Found {len(phone_spans)} spans with phone-like patterns:")
                    for span_text in phone_spans[:3]:  # Show first 3
                        print(f"  - {span_text}")
                else:
                    print("No spans with phone-like patterns found")
            
        except Exception as e:
            print(f"Error during test: {e}")
        finally:
            page.close()

if __name__ == "__main__":
    test_phone_reveal()
