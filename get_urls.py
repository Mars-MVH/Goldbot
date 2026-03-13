from curl_cffi import requests
import re
import json

try:
    s = requests.Session(impersonate='chrome')
    
    html1 = s.get('https://www.hollandgold.nl/goud-kopen/gouden-munten.html').text
    print('Krug:', set(re.findall(r'https://www.hollandgold.nl/[^\"]*krugerrand[^\"]*\.html', html1)))
    
    html2 = s.get('https://www.hollandgold.nl/zilver-kopen/zilveren-munten.html').text
    print('Maple:', set(re.findall(r'https://www.hollandgold.nl/[^\"]*maple-leaf[^\"]*\.html', html2)))
    
    html3 = s.get('https://www.hollandgold.nl/zilver-kopen/zilverstaven-kopen.html').text
    print('Zilverbaar:', set(re.findall(r'https://www.hollandgold.nl/[^\"]*1-kilo[^\"]*\.html', html3)))
    
    html4 = s.get('https://www.hollandgold.nl/goud-kopen/goudbaren-kopen.html').text
    print('Goudbaar:', set(re.findall(r'https://www.hollandgold.nl/[^\"]*1-troy-ounce[^\"]*\.html', html4)))

except Exception as e:
    print(e)
