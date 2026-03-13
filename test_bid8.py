from curl_cffi import requests
import re
from bs4 import BeautifulSoup
import traceback

s = requests.Session(impersonate='chrome120')

try:
    print("=== HG GOUD INKOOP ===")
    html = s.get('https://www.hollandgold.nl/goud-verkopen/gouden-munten-verkopen.html', timeout=10).text
    soup = BeautifulSoup(html, 'html.parser')
    
    # Vind alle producten op de inkooplijst
    products = soup.find_all('li', class_='item product product-item')
    if not products:
        products = soup.find_all('div', class_='product-item-info')
        
    for p in products:
        name_tag = p.find('a', class_='product-item-link')
        price_tag = p.find('span', class_='price')
        if name_tag and price_tag:
            print(f"{name_tag.text.strip()}: {price_tag.text.strip()}")
            
    print("\n=== HG ZILVER INKOOP ===")
    html2 = s.get('https://www.hollandgold.nl/zilver-verkopen/zilveren-munten-verkopen.html', timeout=10).text
    soup2 = BeautifulSoup(html2, 'html.parser')
    products2 = soup2.find_all('li', class_='item product product-item')
    if not products2:
        products2 = soup2.find_all('div', class_='product-item-info')
        
    for p in products2:
        name_tag = p.find('a', class_='product-item-link')
        price_tag = p.find('span', class_='price')
        if name_tag and price_tag:
            print(f"{name_tag.text.strip()}: {price_tag.text.strip()}")
            
except Exception as e:
    print(traceback.format_exc())
