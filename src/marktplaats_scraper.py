from bs4 import BeautifulSoup
import time
import random


def get_stealth_session():
    """Maak een stealth HTTP sessie aan (vervangt het verwijderde marktplaats_session module)."""
    try:
        import cloudscraper
        return cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
        )
    except ImportError:
        import requests
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'
        })
        return session


def human_delay(min_sec=1, max_sec=3):
    """Simuleer menselijke vertraging."""
    time.sleep(random.uniform(min_sec, max_sec))

def fetch_ad_description(scraper, url):
    if not url: return ""
    try:
        human_delay(1, 3) # Niet te snel achter elkaar
        print(f"   [🔍] Advertentiedetails ophalen...")
        resp = scraper.get(url, timeout=10)
        resp.raise_for_status()
        # Probeer Marktplaats 'Description' block te vinden
        soup = BeautifulSoup(resp.text, 'html.parser')
        desc_div = soup.find(class_=lambda c: c and 'Description' in c)
        if desc_div:
            return desc_div.get_text(separator=' ', strip=True)
            
        # Fallback naar page meta description
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc and 'content' in meta_desc.attrs:
            return meta_desc['content']
            
        return ""
    except Exception as e:
        print(f"   [⚠️] Kon omschrijving niet ophalen ({e})")
        return ""

def scrape_marktplaats_search(keyword, max_results=5):
    """
    Zoekt op Marktplaats naar een specifiek keyword en haalt de eerste resultaten op.
    Gebruikt de op cookies werkende stealth sessie o.b.v Datadome bypas.
    """
    results = []
    
    # Haal de stealth sessie op
    scraper = get_stealth_session()
    search_url = f"https://www.marktplaats.nl/q/{keyword.replace(' ', '+')}/"
    
    try:
        # Simuleer een willekeurige vertraging VOOR we Marktplaats raken (mimic human behavior)
        human_delay(1, 4)
        print(f"📡 [MP Radar] Zoeken naar '{keyword}' achter de schermen...")
        
        response = scraper.get(search_url, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Marktplaats web elementen
        listings = soup.select('.hz-Listing, .mp-Listing')
        
        for index, item in enumerate(listings):
            if index >= max_results:
                break
                
            # Marktplaats nieuwe CSS classes (2024-2025)
            title_elem = item.find('strong', class_=lambda c: c and 'hz-Text' in c)
            
            # Prijzen zitten in een hz-Title / h5 structuur
            price_elem = item.find('h5', class_=lambda c: c and 'hz-Title' in c)
            
            # De link is meestal de 'a.hz-Link' met role='link'
            link_elem = item.find('a', class_=lambda c: c and 'hz-Link' in c)
            
            # De thumbnail afbeelding
            img_elem = item.find('img')
            
            # Verkoper badge detectie (Pro / Topverkoper)
            seller_type = "particulier"
            seller_elem = item.find(class_=lambda c: c and ('Badge' in c or 'seller' in c.lower() or 'Seller' in c))
            if seller_elem:
                badge_text = seller_elem.get_text(strip=True).lower()
                if 'pro' in badge_text or 'topverkoper' in badge_text or 'bedrijf' in badge_text:
                    seller_type = "pro"
            
            title = title_elem.text.strip() if title_elem else "Onbekend"
            price_str = price_elem.text.strip() if price_elem else "Bieden"
            url = link_elem.get('href') if link_elem else ""
            img_url = img_elem.get('src') if img_elem else ""
            
            if url and not url.startswith('http'):
                url = "https://www.marktplaats.nl" + url
            
            # Probeer prijs om te zetten naar float voor de logica
            price_value = None
            if '€' in price_str:
                clean_price = price_str.replace('€', '').replace('\xa0', '').replace('.', '').replace(',', '.').strip()
                try:
                    price_value = float(clean_price)
                    # Marktplaats gebruikt soms een punt als duizendseparator, en komma als decimaal.
                    # We moeten dit omzetten naar een punt als decimaal.
                    # E.g., "1.234,56" -> "1234.56"
                    # E.g., "123,45" -> "123.45"
                    # E.g., "1234" -> "1234"
                    # De bovenstaande replace(',', '.') doet dit al correct.
                except ValueError:
                    pass
            
            desc = fetch_ad_description(scraper, url)
            
            results.append({
                "title": title,
                "price_raw": price_str,
                "price_float": price_value,
                "url": url,
                "image_url": img_url,
                "keyword": keyword,
                "description": desc,
                "seller_type": seller_type
            })
            
    except Exception as e:
        print(f"❌ Fout tijdens scrapen Marktplaats: {e}")
        
    return results

def place_marktplaats_bid(url, bid_amount):
    """
    Plaatst een asynchroon bod op Marktplaats via de API / GraphQL endpoint.
    Vereist een geldige 'mp_cookies.json' in de root directory.
    """
    import json
    import re
    import os
    # get_stealth_session is nu lokaal gedefinieerd (bovenaan dit bestand)
    
    if not os.path.exists('mp_cookies.json'):
        return False, "Geen 'mp_cookies.json' gevonden."
        
    item_id = None
    match = re.search(r'[ma](\d+)', url)
    if match:
        item_id = match.group(1)
    else:
        return False, "Kon ID niet onttrekken."
        
    try:
        session = get_stealth_session()
        bid_api_url = f"https://www.marktplaats.nl/v/api/items/{item_id}/bids"
        
        payload = {
            "amount": int(float(bid_amount) * 100), # Centen
            "currency": "EUR"
        }
        
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://www.marktplaats.nl",
            "Referer": url,
            "X-Requested-With": "XMLHttpRequest"
        }
        
        print(f"[🤖 Auto-Bid] Poging om €{bid_amount} te bieden op item {item_id}...")
        response = session.post(bid_api_url, json=payload, headers=headers, timeout=10)
        
        if response.status_code in [200, 201]:
            print(f"✅ [Auto-Bid] Bod van {bid_amount} geplaatst!")
            return True, f"Verzonden: €{bid_amount}"
        elif response.status_code == 401:
            return False, "Cookies verlopen."
        elif response.status_code == 400:
             try:
                 err_msg = response.json().get('message', 'Vaak is het bod te laag.')
                 return False, f"Geweigerd: {err_msg}"
             except:
                 return False, f"Laag Bod Geweigerd"
        else:
            return False, f"API Error {response.status_code}"
            
    except Exception as e:
        print(f"❌ [Auto-Bid] Crash: {e}")
        return False, f"Fout: {e}"
