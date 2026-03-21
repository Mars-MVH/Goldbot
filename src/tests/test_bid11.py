from curl_cffi import requests
import re
from bs4 import BeautifulSoup
import traceback

s = requests.Session(impersonate='chrome120')

try:
    print("=== TSM KRUGERRAND INKOOP PAGE ===")
    html = s.get('https://www.inkoopedelmetaal.nl/goud-verkopen/gouden-munten/krugerrand', timeout=10).text
    soup = BeautifulSoup(html, 'html.parser')
    
    # Try finding the exact price we know (around 4000-5000 EUR)
    spans = soup.find_all(lambda tag: tag.name == "span" and ("4." in tag.text or "4," in tag.text))
    for s_tag in spans:
        if 'price' in s_tag.get('class', []):
            print("Found via class 'price':", s_tag.text.strip())
            
    # Or just search 4-digit numbers with comma and print their parent tags
    m = re.finditer(r'>(.*?4\.\d{3},\d{2}.*?)<', html)
    for m_item in list(m)[:5]:
        print("Regex match:", m_item.group(1).strip())
        
    divs = soup.find_all('div', class_=re.compile("price", re.I))
    for d in divs:
        txt = d.text.strip().replace('\n', ' ')
        if '4.' in txt:
            print("Found div containing 4.:", txt)
except Exception as e:
    print(traceback.format_exc())
