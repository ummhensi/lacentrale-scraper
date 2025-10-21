#!/usr/bin/env python3

import re

def test_regex():
    # Read the actual HTML file
    with open('debug_http/ad_1_no_data.html', 'r') as f:
        html = f.read()
    
    print(f"HTML length: {len(html)}")
    
    # Test CLASSIFIED_MAIN_INFOS regex
    pattern1 = r"var\s+CLASSIFIED_MAIN_INFOS\s*=\s*(\{[\s\S]*?\})\s*;"
    match1 = re.search(pattern1, html)
    print(f"CLASSIFIED_MAIN_INFOS match: {match1 is not None}")
    if match1:
        print(f"Match length: {len(match1.group(1))}")
        print(f"First 100 chars: {match1.group(1)[:100]}")
    
    # Test SummaryInformationData regex
    pattern2 = r"var\s+SummaryInformationData\s*=\s*(\{[\s\S]*?\})\s*;"
    match2 = re.search(pattern2, html)
    print(f"SummaryInformationData match: {match2 is not None}")
    if match2:
        print(f"Match length: {len(match2.group(1))}")
        print(f"First 100 chars: {match2.group(1)[:100]}")

if __name__ == "__main__":
    test_regex()
