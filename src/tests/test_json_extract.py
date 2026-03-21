from curl_cffi import requests
from bs4 import BeautifulSoup
import json
import re

html = requests.get('https://www.hollandgold.nl/verkopen/gouden-munten.html', impersonate='chrome120').text
soup = BeautifulSoup(html, 'html.parser')

for s in soup.find_all('script'):
    if s.string and 'Krugerrand' in s.string:
        try:
            data = json.loads(s.string)
            dump = json.dumps(data)
            
            print("Found JSON containing Krugerrand!")
            if '4413' in dump or '4414' in dump:
                print(">>> YES! The bid price (~4413/4414) was found in the JSON!")
            else:
                print("No bid price found in this JSON block.")
                
            prices = re.findall(r'"price":\s*"?([\d.,]+)"?', dump)
            print("Extracted prices near Krugerrand context:")
            print(prices[:10])
        except Exception as e:
            pass
