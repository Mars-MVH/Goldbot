from curl_cffi import requests
import re
import traceback

s = requests.Session(impersonate='chrome120')

try:
    print("--- TSM ---")
    r_tsm = s.get('https://www.inkoopedelmetaal.nl/gouden-krugerrand-1-troy-ounce-verkopen', timeout=10)
    # Find surrounding HTML for "Krugerrand"
    matches = re.finditer(r'(.{0,100}Krugerrand.{0,200})', r_tsm.text, re.IGNORECASE | re.DOTALL)
    for i, m in enumerate(matches):
        if i > 5: break
        print(f"TSM Match {i}: {m.group(1).strip()}")

    print("\n--- HG GOUD ---")
    r_hg = s.get('https://www.hollandgold.nl/goud-verkopen/gouden-munten-verkopen.html', timeout=10)
    matches_hg = re.finditer(r'(.{0,100}Krugerrand.{0,300})', r_hg.text, re.IGNORECASE | re.DOTALL)
    for i, m in enumerate(matches_hg):
        if 'price' in m.group(1).lower() or '€' in m.group(1):
            print(f"HG Match {i}: {m.group(1).strip()}")
            break
            
except Exception as e:
    print(traceback.format_exc())
