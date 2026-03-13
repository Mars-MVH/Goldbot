import asyncio
from curl_cffi import requests
import os
import sys

# voeg path toe zodat imports werken
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dealer_scraper import _scrape_price_resilient

def test():
    session = requests.Session(impersonate="chrome120")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
    }
    
    print("\n--- 101 Munten 1KG ---")
    urls = ["https://www.101munten.nl/product/zilver/1-kg-umicore-zilverbaar/"]
    p, u = _scrape_price_resilient(session, urls, headers)
    print("Prijs:", p, "URL:", u)

    print("\n--- TSM Krugerrand Goud ---")
    urls2 = ["https://www.thesilvermountain.nl/nl/krugerrand-1-troy-ounce-gouden-munt", "https://www.thesilvermountain.nl/1-troy-ounce-gouden-krugerrand-munt"]
    p2, u2 = _scrape_price_resilient(session, urls2, headers)
    print("Prijs:", p2, "URL:", u2)

if __name__ == "__main__":
    test()
