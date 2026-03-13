import os
import re
import json
import asyncio
from bs4 import BeautifulSoup
from curl_cffi import requests

# Base directory for data
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

INDEX_FILE = os.path.join(DATA_DIR, "dealer_urls.json")

SOURCES = {
    "Holland Gold": "https://www.hollandgold.nl/sitemap.xml",
    "The Silver Mountain": "https://www.thesilvermountain.nl/sitemap.xml", # Vaak de root voor Magento/Yoast
    "101 Munten": "https://www.101munten.nl/sitemap_index.xml", # Aangepast naar de root sitemap o.b.v. robots.txt
    "TSM Inkoop": "https://www.inkoopedelmetaal.nl/sitemap.xml"
}

# Regex patterns for matching
YEAR_PATTERN = re.compile(r'\b(201\d|202\d|203\d)\b')
WEIGHT_PATTERN = re.compile(r'\b(1[-_]troy[-_]ounce|1[-_]oz|1[-_]kilo|1[-_]kg|100[-_]gram)\b')
BRAND_PATTERN = re.compile(r'\b(umicore|c[-_]hafner|heraeus|valcambi|perth[-_]mint|royal[-_]canadian[-_]mint|royal[-_]mint)\b', re.IGNORECASE)
PRODUCT_PATTERN = re.compile(r'\b(krugerrand|maple[-_]leaf|philharmoniker|goudbaar|zilverbaar|britannia|kangaroo)\b', re.IGNORECASE)
EXCLUDE_PATTERN = re.compile(r'\b(incuse|proof|zilverbaar-munt|gilded|box|jubileum|set|colored|blister)\b', re.IGNORECASE)
PREOWNED_PATTERN = re.compile(r'\b(pre[-_]owned|circulated|b[-_]keus|tweedehands)\b', re.IGNORECASE)

def _clean_url(url):
    return url.strip().split('?')[0]

async def fetch_sitemap_urls(session, name, sitemap_url):
    print(f"🌍 Downloading sitemap for {name}...")
    try:
        response = session.get(sitemap_url, timeout=30)
        response.raise_for_status()
        
        # Sitemaps can be sitemap indexes or direct urlsets
        root = BeautifulSoup(response.content, 'xml')
        urls = []
        
        # Check if it's a sitemap index
        sitemaps = root.find_all('sitemap')
        if sitemaps:
            print(f"  └ Found {len(sitemaps)} sub-sitemaps. Parsing them...")
            for sm in sitemaps:
                loc = sm.find('loc')
                if loc and loc.text:
                    sub_urls = await fetch_sitemap_urls(session, name, loc.text)
                    urls.extend(sub_urls)
            return urls
            
        # Standard URL set
        for url_node in root.find_all('url'):
            loc = url_node.find('loc')
            if loc and loc.text:
                urls.append(_clean_url(loc.text))
        
        print(f"  └ Extracted {len(urls)} URLs from {sitemap_url}")
        return urls
    except Exception as e:
        print(f"⚠️ Failed to fetch sitemap {sitemap_url}: {e}")
        return []

def organize_urls(urls, dealer_name):
    """Filtert en categoriseert URL's in het geheugen"""
    database = {}
    
    count = 0
    for url in urls:
        # We negeren URLs die geen nuttige keywords bevatten
        url_lower = url.lower()
        if not ("goud" in url_lower or "zilver" in url_lower or "ounce" in url_lower or "kilo" in url_lower):
            continue
            
        # Sla "speciale" edities over zoals incuse, proof, box, etc.
        if EXCLUDE_PATTERN.search(url_lower):
            continue
            
        # Is het een pre-owned / B-keus variant?
        conditie = "preowned" if PREOWNED_PATTERN.search(url_lower) else "nieuw"
            
        # Verwijder domein voor metaal check om valse hits (zoals hollandGOUD) te voorkomen
        url_path = url_lower.replace("hollandgold.nl", "").replace("thesilvermountain.nl", "").replace("inkoopedelmetaal.nl", "")
        
        metaal = "unknown"
        if "goud" in url_path or "gold" in url_path: metaal = "gold"
        elif "zilver" in url_path or "silver" in url_path: metaal = "silver"
        
        soort = "unknown"
        if "baar" in url_lower or "bar" in url_lower: soort = "baar"
        elif "munt" in url_lower or "coin" in url_lower or "krugerrand" in url_lower or "maple" in url_lower: soort = "munt"
        
        # Haal metadata uit de URL slug
        # Bijv: "1-troy-ounce-gouden-maple-leaf-2024"
        
        # Jaartal?
        jaartal = "diverse"
        y_match = YEAR_PATTERN.search(url_lower)
        if y_match:
            jaartal = y_match.group(1)
            
        # Merk?
        merk = "unknown"
        b_match = BRAND_PATTERN.search(url_lower)
        if b_match:
            merk = b_match.group(1).replace("-", " ").replace("_", " ").title()
            
        # Specifieke Munt?
        product = "unknown"
        p_match = PRODUCT_PATTERN.search(url_lower)
        if p_match:
            product = p_match.group(1).replace("-", " ").replace("_", " ").title()
            
        # Gewicht?
        gewicht = "unknown"
        w_match = WEIGHT_PATTERN.search(url_lower)
        if w_match:
            w = w_match.group(1).replace("-", " ").replace("_", " ")
            if "1 troy ounce" in w or "1 oz" in w: gewicht = "1_oz"
            if "1 kilo" in w or "1 kg" in w: gewicht = "1_kg"
            if "100 gram" in w: gewicht = "100_gr"
            
        if metaal == "unknown" or soort == "unknown" or product == "unknown":
            continue
            
        # Maak unieke sleutel
        # Voorbeeld: "gold_munt_1_oz_maple leaf_2024_n/a_nieuw"
        
        key = f"{metaal}_{soort}_{gewicht}_{product.lower()}_{jaartal}_{merk.lower()}_{conditie}"
        
        if key not in database:
            database[key] = url
            count += 1
            
        # [Fallback Logic] Als het een specifiek jaartal heeft (bijv. 2024), 
        # schrijf deze dan ook pro-actief weg als "Diverse Jaartallen" variant, óf als
        # het voorgaande jaar (2023) voor het geval dealers hun oude voorraad als "diverse" verkopen.
        if jaartal != "diverse" and jaartal.isdigit():
            y_int = int(jaartal)
            # Create a fallback for Year-1
            key_prev_year = f"{metaal}_{soort}_{gewicht}_{product.lower()}_{y_int - 1}_{merk.lower()}_{conditie}"
            if key_prev_year not in database:
                database[key_prev_year] = url
            
            # Create a fallback for 'diverse'
            key_diverse = f"{metaal}_{soort}_{gewicht}_{product.lower()}_diverse_{merk.lower()}_{conditie}"
            if key_diverse not in database:
                database[key_diverse] = url
            
    print(f"✅ {dealer_name} geïndexeerd: {count} specifieke producten geklasseerd.")
    return database

async def build_index():
    print("🚀 Start Nachtelijke Dealer Indexering...")
    
    session = requests.Session(impersonate="chrome120")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
    }
    session.headers.update(headers)
    
    master_index = {
        "Holland Gold": {},
        "The Silver Mountain": {},
        "101 Munten": {},
        "TSM Inkoop": {}
    }
    
    for dealer, sm_url in SOURCES.items():
        all_urls = await fetch_sitemap_urls(session, dealer, sm_url)
        if all_urls:
            master_index[dealer] = organize_urls(all_urls, dealer)
            
    # Sla op naar disk
    with open(INDEX_FILE, 'w', encoding='utf-8') as f:
        json.dump(master_index, f, indent=4, ensure_ascii=False)
        
    print(f"🎉 Indexering voltooid! Data opgeslagen in {INDEX_FILE}")

if __name__ == "__main__":
    asyncio.run(build_index())
