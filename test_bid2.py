from curl_cffi import requests
import re
s = requests.Session(impersonate='chrome120')
try:
    print("--- TSM ---")
    r_tsm = s.get('https://www.inkoopedelmetaal.nl/gouden-krugerrand-1-troy-ounce-verkopen', timeout=10)
    m_tsm = re.search(r'price[^>]*>.*?(\d+[\.,]\d{2})', r_tsm.text, re.DOTALL)
    if m_tsm:
        print('TSM:', m_tsm.group(1))
    
    # Try Maple Leaf Zilver 1 oz too
    r_tsm2 = s.get('https://www.inkoopedelmetaal.nl/1-troy-ounce-zilveren-maple-leaf-verkopen', timeout=10)
    m_tsm2 = re.search(r'price[^>]*>.*?(\d+[\.,]\d{2})', r_tsm2.text, re.DOTALL)
    if m_tsm2:
        print('TSM Zilver:', m_tsm2.group(1))

    print("--- HG ---")
    r_hg = s.get('https://www.hollandgold.nl/goud-verkopen/gouden-munten-verkopen.html', timeout=10)
    # the page is a list of coins, we need to find krugerrand
    m_hg = re.search(r'Krugerrand.*?<span class="price">\s*[^0-9]*([\d\.,]+)', r_hg.text, re.DOTALL | re.IGNORECASE)
    print('HG Krugerrand:', m_hg.group(1) if m_hg else 'Not found')

    r_hg2 = s.get('https://www.hollandgold.nl/zilver-verkopen/zilveren-munten-verkopen.html', timeout=10)
    m_hg2 = re.search(r'Maple Leaf.*?<span class="price">\s*[^0-9]*([\d\.,]+)', r_hg2.text, re.DOTALL | re.IGNORECASE)
    print('HG Maple Leaf:', m_hg2.group(1) if m_hg2 else 'Not found')
except Exception as e:
    print(e)
