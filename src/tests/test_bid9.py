from curl_cffi import requests
import re
from bs4 import BeautifulSoup
import traceback

s = requests.Session(impersonate='chrome120')

try:
    print("=== HG REGULAR PRODUCT PAGE ===")
    html = s.get('https://www.hollandgold.nl/krugerrand-1-troy-ounce-gouden-munt.html', timeout=10).text
    soup = BeautifulSoup(html, 'html.parser')
    
    # Let's find all text containing "inkoop" or similar
    prices = re.findall(r'.{0,50}(inkoop|wij kopen|terugkoop).{0,50}', html, re.I)
    print("Found phrases:", prices[:5])
    
    # Look for all elements with class containing 'price'
    spans = soup.find_all(class_=re.compile("price", re.I))
    for span in set([s.text.strip() for s in spans]):
        if '€' in span or 'euro' in span.lower():
            print("Price span:", span)
            
except Exception as e:
    print(traceback.format_exc())
