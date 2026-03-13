from curl_cffi import requests
import re

session = requests.Session(impersonate='chrome120')
r = session.get('https://www.hollandgold.nl/goud-kopen/goudbaren-kopen.html', timeout=10)
print(f"Status: {r.status_code}")

# Find any links containing 'hafner'
links = re.findall(r'href=[\'"]([^\'"]*hafner[^\'"]*)[\'"]', r.text)
for link in set(links):
    print("Found link:", link)

links2 = re.findall(r'href=[\'"]([^\'"]*1-troy-ounce[^\'"]*)[\'"]', r.text)
for link in set(links2):
    print("Found troy ounce link:", link)
