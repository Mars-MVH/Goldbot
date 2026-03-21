from curl_cffi import requests
import re
from bs4 import BeautifulSoup

s = requests.Session(impersonate='chrome120')

urls = [
    "https://www.hollandgold.nl/krugerrand-1-troy-ounce-gouden-munt.html",
    "https://www.hollandgold.nl/maple-leaf-1-troy-ounce-zilver-div-jaartallen.html",
    "https://www.hollandgold.nl/umicore-1-troy-ounce-goudbaar.html",
    "https://www.hollandgold.nl/heraeus-1-kilogram-zilverbaar.html"
]

for u in urls:
    html = s.get(u, timeout=10).text
    soup = BeautifulSoup(html, 'html.parser')
    spans = soup.find_all(class_=re.compile("price", re.I))
    print(f"\n--- {u.split('/')[-1]} ---")
    for span in set([s.text.strip() for s in spans]):
        if '€' in span or 'euro' in span.lower():
            if 'gram' in span.lower() or 'terug' in span.lower():
                print("FOUND BID ELEMENT:", span)
