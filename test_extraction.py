#!/usr/bin/env python3

import json
import re
from bs4 import BeautifulSoup

def _parse_classified_main_infos(html: str):
    try:
        m = re.search(r"var\s+CLASSIFIED_MAIN_INFOS\s*=\s*(\{[\s\S]*?\})\s*;", html)
        if not m:
            return None
        blob = m.group(1)
        return json.loads(blob)
    except Exception:
        return None

def _parse_summary_information_data(html: str):
    try:
        m = re.search(r"var\s+SummaryInformationData\s*=\s*(\{[\s\S]*?\})\s*;", html)
        if not m:
            return None
        blob = m.group(1)
        return json.loads(blob)
    except Exception:
        return None

def test_extraction():
    # Load the debug JSON file
    with open('debug_http/script_data_0.json', 'r') as f:
        debug_data = json.load(f)
    
    classified_main_infos = debug_data.get('classified_main_infos')
    summary_info = debug_data.get('summary_info')
    
    print("=== DEBUGGING EXTRACTION ===")
    print(f"classified_main_infos found: {classified_main_infos is not None}")
    print(f"summary_info found: {summary_info is not None}")
    
    if summary_info:
        print("\n=== SUMMARY INFO STRUCTURE ===")
        print(f"Keys in summary_info: {list(summary_info.keys())}")
        
        # Check sellerInfos
        seller_infos = summary_info.get('sellerInfos', {})
        print(f"\nSellerInfos keys: {list(seller_infos.keys())}")
        print(f"Seller name: {seller_infos.get('sellerName')}")
        
        # Check address
        address = seller_infos.get('address', {})
        print(f"Address keys: {list(address.keys())}")
        print(f"Address: {address}")
        
        # Check classified data
        classified = summary_info.get('classified', {})
        print(f"\nClassified keys: {list(classified.keys())}")
        
        # Check vehicle data
        vehicle = classified.get('vehicle', {})
        print(f"Vehicle keys: {list(vehicle.keys())}")
        
        if 'combined' in vehicle:
            combined = vehicle['combined']
            print(f"Combined keys: {list(combined.keys())}")
            
            if 'specs' in combined:
                specs = combined['specs']
                print(f"Specs keys: {list(specs.keys())}")
                print(f"Gearbox: {specs.get('gearbox')}")
                print(f"Energy: {specs.get('energy')}")
                print(f"NbOfDoors: {specs.get('nbOfDoors')}")
                print(f"SeatingCapacity: {specs.get('seatingCapacity')}")
                print(f"FiscalHorsePower: {specs.get('fiscalHorsePower')}")
                print(f"PowerDin: {specs.get('powerDin')}")
                
                # Check critair
                critair = specs.get('critair', {})
                print(f"Critair: {critair}")
                
                # Check consumption
                consumption = specs.get('consumption', {})
                print(f"Consumption: {consumption}")
                
                # Check co2
                co2 = specs.get('co2', {})
                print(f"CO2: {co2}")
    
    # Test phone extraction
    print("\n=== PHONE EXTRACTION TEST ===")
    if summary_info:
        seller_infos = summary_info.get('sellerInfos', {})
        print(f"Phone in sellerInfos: {seller_infos.get('phone')}")
        
        classified = summary_info.get('classified', {})
        contacts = classified.get('contacts', {})
        print(f"Contacts: {contacts}")
        
        # Check if there's a phone field anywhere
        def find_phone_recursive(obj, path=""):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if 'phone' in k.lower() or (isinstance(v, str) and re.match(r'^[0-9\s\+\-\(\)]+$', v.strip())):
                        print(f"Found potential phone at {path}.{k}: {v}")
                    find_phone_recursive(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    find_phone_recursive(item, f"{path}[{i}]")
        
        print("Searching for phone numbers recursively...")
        find_phone_recursive(summary_info, "summary_info")

if __name__ == "__main__":
    test_extraction()
