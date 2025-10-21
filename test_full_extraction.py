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

def extract_ad_details_test(page_content: str, url: str):
    """
    Test version of extract_ad_details to debug the issue
    """
    result = {
        "title": None,
        "price_eur": None,
        "mileage_km": None,
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
        
        print(f"classified_main_infos found: {classified_main_infos is not None}")
        print(f"summary_info found: {summary_info is not None}")
        
        if classified_main_infos or summary_info:
            print("Using script block data")
            
            # Extract from SummaryInformationData
            if summary_info:
                try:
                    # Agency name
                    seller_infos = summary_info.get("sellerInfos", {})
                    if isinstance(seller_infos, dict):
                        seller_name = seller_infos.get("sellerName")
                        if isinstance(seller_name, str) and seller_name.strip():
                            result["agency_name"] = seller_name.strip()
                            print(f"Agency name extracted: {result['agency_name']}")

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
                            print(f"Address extracted: {result['address']}")

                except Exception as exc:
                    print(f"SummaryInformationData extraction failed: {exc}")

            # Extract characteristics from script block data
            if summary_info:
                try:
                    def gv(obj, path):
                        cur = obj
                        for p in path:
                            if not isinstance(cur, dict):
                                return None
                            cur = cur.get(p)
                        return cur
                    
                    # Get vehicle specs from SummaryInformationData
                    vehicle_specs = gv(summary_info, ["classified", "vehicle", "combined", "specs"])
                    vehicle_version = gv(summary_info, ["classified", "vehicle", "combined", "version"])
                    
                    print(f"vehicle_specs found: {vehicle_specs is not None}")
                    print(f"vehicle_version found: {vehicle_version is not None}")
                    
                    if isinstance(vehicle_specs, dict):
                        parts = []
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
                            print(f"Characteristics extracted: {len(parts)} fields")
                            print(f"First few characteristics: {parts[:3]}")
                except Exception as exc:
                    print(f"Characteristics extraction failed: {exc}")

            # If we have data from script blocks, return early
            if result.get("title") or result.get("price_eur"):
                print("Returning early due to title/price found")
                return result
        else:
            print("No script blocks found, would fallback to __NEXT_DATA__")
            
    except Exception as exc:
        print(f"Failed to parse data for {url}: {exc}")
        return result

    return result

def test_extraction():
    # Load the debug JSON file to simulate the script block data
    with open('debug_http/script_data_0.json', 'r') as f:
        debug_data = json.load(f)
    
    # Create a mock HTML with the script blocks
    mock_html = f"""
    <html>
    <script>
    var CLASSIFIED_MAIN_INFOS = {json.dumps(debug_data['classified_main_infos'])};
    </script>
    <script>
    var SummaryInformationData = {json.dumps(debug_data['summary_info'])};
    </script>
    </html>
    """
    
    result = extract_ad_details_test(mock_html, "test_url")
    
    print("\n=== FINAL RESULT ===")
    for key, value in result.items():
        if value is not None:
            print(f"{key}: {value}")
        else:
            print(f"{key}: None")

if __name__ == "__main__":
    test_extraction()
