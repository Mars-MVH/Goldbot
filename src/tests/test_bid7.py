from curl_cffi import requests
import re
s = requests.Session(impersonate='chrome120')

print("=== TSM SITEMAP ===")
try:
    r = s.get('https://www.inkoopedelmetaal.nl/sitemap.xml')
    # If sitemap index, fetch first one
    sub_urls = re.findall(r'<loc>(.*?(verkopen|sitemap).*?)</loc>', r.text)
    for index_url, _ in sub_urls[:2]:
        if "sitemap" in index_url:
            print(f"Fetching sub-sitemap: {index_url}")
            r2 = s.get(index_url)
            matches = re.findall(r'<loc>(.*?(verkopen|krugerrand|maple|baar).*?)</loc>', r2.text)
            for m in matches[:5]:
                print(m[0])
        else:
            print(index_url)
except: pass

print("=== HG SITEMAP ===")
try:
    r = s.get('https://www.hollandgold.nl/media/sitemap/sitemap-1-1.xml')
    matches = re.findall(r'<loc>(.*?verkopen.*?)</loc>', r.text)
    print("Found HG links:", len(matches))
    for m in matches[:5]:
        print(m)
    
    # Also look for krugerrand and verkopen
    krugs = [m for m in matches if 'krugerrand' in m.lower()]
    print("Krugs:", krugs[:2])
except: pass
