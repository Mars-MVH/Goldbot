from curl_cffi import requests
import re
s = requests.Session(impersonate='chrome120')

try:
    r = s.get('https://www.inkoopedelmetaal.nl/gouden-krugerrand-1-troy-ounce-verkopen', timeout=10)
    with open('tsm_bid.html', 'w', encoding='utf-8') as f:
        f.write(r.text)
        
    r2 = s.get('https://www.hollandgold.nl/goud-verkopen/gouden-munten-verkopen/krugerrand-1-troy-ounce-gouden-munt.html', timeout=10)
    with open('hg_bid.html', 'w', encoding='utf-8') as f:
        f.write(r2.text)
        
    print("Files written. Searching for EUR sizes:")
    
    # Let's search for 4-digit numbers with comma (e.g. 2.750,00 or 2750,00)
    prices_tsm = re.findall(r'.{0,30}(\d{1,2}\.?\d{3},\d{2}).{0,30}', r.text)
    print("TSM 4-digit prices:", prices_tsm[:10])
    
    prices_hg = re.findall(r'.{0,30}(\d{1,2}\.?\d{3},\d{2}).{0,30}', r2.text)
    print("HG 4-digit prices:", prices_hg[:10])
    
except Exception as e:
    print(e)
