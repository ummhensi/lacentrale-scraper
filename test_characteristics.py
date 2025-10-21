#!/usr/bin/env python3

import json

def test_characteristics_extraction():
    # Load the debug JSON file
    with open('debug_http/script_data_0.json', 'r') as f:
        debug_data = json.load(f)
    
    summary_info = debug_data.get('summary_info')
    
    if not summary_info:
        print("No summary_info found")
        return
    
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
    
    print(f"vehicle_specs: {vehicle_specs}")
    print(f"vehicle_version: {vehicle_version}")
    
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
            print(f"{label} ({path}): {val}")
            if val is not None:
                parts.append(f"{label}: {val}")
        
        # Add version info
        if isinstance(vehicle_version, dict):
            for key, label in [("make", "Marque"), ("model", "Modèle"), ("commercialModel", "Modèle commercial"), ("trimLevel", "Finition")]:
                val = vehicle_version.get(key)
                print(f"{label} ({key}): {val}")
                if val is not None:
                    parts.append(f"{label}: {val}")
        
        # Add first traffic date
        first_traffic = gv(summary_info, ["classified", "vehicle", "combined", "firstTrafficDate"])
        print(f"Mise en circulation: {first_traffic}")
        if first_traffic:
            parts.append(f"Mise en circulation: {first_traffic}")
        
        print(f"\nFinal characteristics: {' | '.join(parts)}")
        print(f"Number of characteristics: {len(parts)}")

if __name__ == "__main__":
    test_characteristics_extraction()
