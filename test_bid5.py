from curl_cffi import requests
import re
s = requests.Session(impersonate='chrome120')
try:
    print("--- HG GOUD INKOOP LINKS ---")
    r_hg = s.get('https://www.hollandgold.nl/goud-verkopen/gouden-munten-verkopen.html', timeout=10)
    links = re.findall(r'href="([^"]+krugerrand[^"]+)"', r_hg.text, re.IGNORECASE)
    print("Krugerrand links:", set(links))
    
    print("--- HG ZILVER INKOOP LINKS ---")
    r_hg_z = s.get('https://www.hollandgold.nl/zilver-verkopen/zilveren-munten-verkopen.html', timeout=10)
    links_z = re.findall(r'href="([^"]+maple[^"]+)"', r_hg_z.text, re.IGNORECASE)
    print("Maple links:", set(links_z))
except Exception as e:
    print(e)
