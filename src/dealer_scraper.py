import random
import re
import time

import json
from database import get_price_cache, set_price_cache
from pricing import get_live_spot_prices

# ============================================================
# DEALER PREMIUM CACHE
# ============================================================
# RAM cache _premium_cache is vervangen door SQLite database cache in database.py

# ============================================================
# DEALER PREMIUMS PER PRODUCTCATEGORIE
# Bron: handmatige checks op dealer websites, IEX forum,
# Het Zilver Forum, Reddit r/pmsforsale (NL/BE/DE dealers)
# 
# Format per dealer:
#   ask_premiums = {categorie: percentage boven spot}
#   bid_premiums = {categorie: percentage vs spot (negatief = korting)}
# ============================================================
import os
INDEX_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "dealer_urls.json")
_dealer_index_cache = None

def _get_dealer_index():
    global _dealer_index_cache
    if _dealer_index_cache is None:
        try:
            if os.path.exists(INDEX_FILE):
                import json
                with open(INDEX_FILE, 'r', encoding='utf-8') as f:
                    _dealer_index_cache = json.load(f)
            else:
                _dealer_index_cache = {}
        except Exception as e:
            print(f"⚠️ Error loading dealer index: {e}")
            _dealer_index_cache = {}
    return _dealer_index_cache

def _find_urls(dealer_name, pre_scan_data, fallback_urls, force_jaartal=None, default_product=None):
    if not pre_scan_data: return fallback_urls
    
    idx = _get_dealer_index()
    if dealer_name not in idx or not idx[dealer_name]: return fallback_urls
    
    metaal = pre_scan_data.get("metaal", "unknown").lower()
    if metaal == "goud": metaal = "gold"
    elif metaal == "zilver": metaal = "silver"
    
    soort = pre_scan_data.get("type", "unknown").lower()
    try:
        gewicht_oz = float(pre_scan_data.get("gewicht_oz", 1.0))
    except:
        gewicht_oz = 1.0
        
    gewicht = "unknown"
    if 0.95 <= gewicht_oz <= 1.05: gewicht = "1_oz"
    elif 32.0 <= gewicht_oz <= 32.2: gewicht = "1_kg"
    elif 3.2 <= gewicht_oz <= 3.22: gewicht = "100_gr"
    
    product = default_product or pre_scan_data.get("merk_of_muntnaam", "unknown")
    product = str(product).lower().replace("-", " ").replace("_", " ")
    
    jaartal = force_jaartal or str(pre_scan_data.get("jaartal", "diverse")).lower()
    if jaartal == "onbekend": jaartal = "diverse"
    
    merk = pre_scan_data.get("merk_of_muntnaam", "unknown")
    merk = str(merk).lower().replace("-", " ").replace("_", " ")

    base_keys = [
        f"{metaal}_{soort}_{gewicht}_{product}_{jaartal}_{merk}",
        f"{metaal}_{soort}_{gewicht}_{product}_{jaartal}_unknown",
    ]
    
    if jaartal != "diverse" and jaartal.isdigit():
        y_int = int(jaartal)
        # Prioritize ±2 years spread before falling back to generic 'diverse'
        base_keys.extend([
            f"{metaal}_{soort}_{gewicht}_{product}_{y_int - 1}_{merk}",
            f"{metaal}_{soort}_{gewicht}_{product}_{y_int - 1}_unknown",
            f"{metaal}_{soort}_{gewicht}_{product}_{y_int + 1}_{merk}",
            f"{metaal}_{soort}_{gewicht}_{product}_{y_int + 1}_unknown",
            f"{metaal}_{soort}_{gewicht}_{product}_{y_int - 2}_{merk}",
            f"{metaal}_{soort}_{gewicht}_{product}_{y_int - 2}_unknown",
        ])
        
    base_keys.extend([
        f"{metaal}_{soort}_{gewicht}_{product}_diverse_{merk}",
        f"{metaal}_{soort}_{gewicht}_{product}_diverse_unknown",
        f"{metaal}_{soort}_{gewicht}_unknown_{jaartal}_{merk}",
        f"{metaal}_{soort}_{gewicht}_unknown_diverse_{merk}"
    ])
    
    possible_keys = []
    for bk in base_keys:
        possible_keys.append(f"{bk}_preowned")
        possible_keys.append(f"{bk}_nieuw")
    
    mapping = idx[dealer_name]
    for k in possible_keys:
        if k in mapping:
            print(f"🎯 [Apples to Apples] Match voor {dealer_name}: {k}")
            return [mapping[k]]
            
    return fallback_urls

DEALER_PROFILES = [
    {
        "name": "The Silver Mountain",
        "country": "NL",
        "shipping_nl": 0,
        "ask_premiums": {
            "goud_munt":        4.2,
            "goud_baar":        2.8,
            "zilver_munt":      22.0,   # Incl. marge-regeling BTW
            "zilver_baar":      16.0,
            "zilver_collectible": 28.0,
        },
        # bid_premiums: % boven/onder spotprijs dat dealers betalen bij inkoop
        # Gecalibreerd: HollandGold betaalt €82.32/oz voor 2oz zilver munt
        # bij spot €73.92 = +11.4% boven spot
        "bid_premiums": {
            "goud_munt":        -1.0,
            "goud_baar":        -0.8,
            "zilver_munt":      12.0,   # ~€82/oz bij spot €73.92
            "zilver_baar":      6.0,    # Baren hebben lagere inkoop premium
            "zilver_collectible": 15.0,  # Collectibles behouden hogere premium
        }
    },
    {
        "name": "Goudwisselkantoor",
        "country": "NL",
        "shipping_nl": 0,
        "ask_premiums": {
            "goud_munt":        5.0,
            "goud_baar":        3.5,
            "zilver_munt":      25.0,
            "zilver_baar":      18.0,
            "zilver_collectible": 32.0,
        },
        "bid_premiums": {
            "goud_munt":        -2.0,
            "goud_baar":        -1.5,
            "zilver_munt":      10.0,
            "zilver_baar":      5.0,
            "zilver_collectible": 13.0,
        }
    },
    {
        "name": "Goudonline.nl",
        "country": "NL",
        "shipping_nl": 0,
        "ask_premiums": {
            "goud_munt":        4.5,
            "goud_baar":        3.0,
            "zilver_munt":      20.0,
            "zilver_baar":      15.0,
            "zilver_collectible": 26.0,
        },
        "bid_premiums": {
            "goud_munt":        -1.5,
            "goud_baar":        -1.2,
            "zilver_munt":      10.0,
            "zilver_baar":      4.0,
            "zilver_collectible": 12.0,
        }
    },
    {
        "name": "101 Munten",
        "country": "NL",
        "shipping_nl": 0,
        "ask_premiums": {
            "goud_munt":        3.8,
            "goud_baar":        2.5,
            "zilver_munt":      19.0,
            "zilver_baar":      14.0,
            "zilver_collectible": 24.0,
        },
        "bid_premiums": {
            "goud_munt":        -1.8,
            "goud_baar":        -1.5,
            "zilver_munt":      9.0,
            "zilver_baar":      3.0,
            "zilver_collectible": 11.0,
        }
    },
    {
        "name": "Goud999",
        "country": "BE",
        "shipping_nl": 9.95,
        "ask_premiums": {
            "goud_munt":        4.1,
            "goud_baar":        2.6,
            "zilver_munt":      20.0,
            "zilver_baar":      15.0,
            "zilver_collectible": 26.0,
        },
        "bid_premiums": {
            "goud_munt":        -1.1,
            "goud_baar":        -0.9,
            "zilver_munt":      11.0,
            "zilver_baar":      5.0,
            "zilver_collectible": 14.0,
        }
    },
    {
        "name": "Goudmunter",
        "country": "BE",
        "shipping_nl": 9.95,
        "ask_premiums": {
            "goud_munt":        4.3,
            "goud_baar":        3.0,
            "zilver_munt":      21.0,
            "zilver_baar":      16.0,
            "zilver_collectible": 28.0,
        },
        "bid_premiums": {
            "goud_munt":        -1.3,
            "goud_baar":        -1.0,
            "zilver_munt":      -3.5,
            "zilver_baar":      -4.5,
            "zilver_collectible": -5.5,
        }
    },
    {
        "name": "Goldsilver.be",
        "country": "BE",
        "shipping_nl": 9.95,
        "ask_premiums": {
            "goud_munt":        3.5,
            "goud_baar":        2.2,
            "zilver_munt":      18.0,
            "zilver_baar":      13.0,
            "zilver_collectible": 24.0,
        },
        "bid_premiums": {
            "goud_munt":        -2.5,
            "goud_baar":        -2.0,
            "zilver_munt":      -5.0,
            "zilver_baar":      -6.0,
            "zilver_collectible": -7.0,
        }
    },
    {
        "name": "MP-Edelmetalle",
        "country": "DE",
        "shipping_nl": 14.90,
        "ask_premiums": {
            "goud_munt":        3.9,
            "goud_baar":        2.4,
            "zilver_munt":      18.0,
            "zilver_baar":      12.0,
            "zilver_collectible": 22.0,
        },
        "bid_premiums": {
            "goud_munt":        -1.9,
            "goud_baar":        -1.5,
            "zilver_munt":      -4.0,
            "zilver_baar":      -5.0,
            "zilver_collectible": -6.0,
        }
    },
    {
        "name": "Kettner Edelmetalle",
        "country": "DE",
        "shipping_nl": 14.90,
        "ask_premiums": {
            "goud_munt":        4.4,
            "goud_baar":        3.2,
            "zilver_munt":      22.0,
            "zilver_baar":      16.0,
            "zilver_collectible": 30.0,
        },
        "bid_premiums": {
            "goud_munt":        -1.4,
            "goud_baar":        -1.0,
            "zilver_munt":      -3.0,
            "zilver_baar":      -4.0,
            "zilver_collectible": -5.0,
        }
    },
    {
        "name": "Inkoop Edelmetaal",
        "country": "NL",
        "sell_only": True,  # Koopt alleen in, verkoopt niet aan particulieren
        "ask_premiums": {},  # Geen verkoopprijzen
        "bid_premiums": {
            "goud_munt":        -0.5,    # Sterke inkoper
            "goud_baar":        -0.3,
            "zilver_munt":      -1.5,
            "zilver_baar":      -2.0,
            "zilver_collectible": -3.0,
        }
    },
]


def _determine_product_category(pre_scan_data):
    """
    Bepaalt de productcategorie voor premium lookup.
    Returns: 'goud_munt', 'goud_baar', 'zilver_munt', 'zilver_baar', 'zilver_collectible'
    """
    if not pre_scan_data:
        return "goud_munt"
    
    metaal = pre_scan_data.get("metaal", "Goud").lower()
    ptype = pre_scan_data.get("type", "Munt").lower()
    subtype = pre_scan_data.get("product_subtype", "plain").lower()
    
    if "zilver" in metaal:
        if subtype in ("collectible", "limited_edition"):
            return "zilver_collectible"
        if "coinbar" in ptype:
            return "zilver_collectible"
        if "baar" in ptype or "bar" in ptype:
            return "zilver_baar"
        return "zilver_munt"
    else:
        if "baar" in ptype or "bar" in ptype:
            return "goud_baar"
        return "goud_munt"


# ============================================================
# SELF-HEALING SCRAPE HELPER
# ============================================================

def _resolve_url_from_sitemap(session, url, target_label):
    """
    Fallback mechanisme: Als een URL 404 geeft, zoek in de sitemap 
    naar de nieuwe URL op basis van domein en product-kenmerken.
    """
    try:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.replace("www.", "")
        
        # Bepaal zoektermen op basis van label
        label_lower = target_label.lower()
        keywords = []
        if "goudbaar" in label_lower:
            keywords = ["goudbaar", "troy-ounce"] # Let op: sommige dealers gebruiken 1-oz
        elif "zilverbaar" in label_lower:
            keywords = ["zilverbaar", "1-kilo"] # 1-kg of 1-kilo (we vangen 1-kg later op indien mist)
        elif "goud" in label_lower:
            keywords = ["krugerrand", "troy-ounce", "goud"]
        elif "zilver" in label_lower:
            keywords = ["maple-leaf", "troy-ounce", "zilver"]
        else:
            return None # Geen zinvolle zoektermen
            
        # Bepaal sitemap URL
        sitemaps = []
        if "hollandgold" in domain:
            sitemaps = ["https://www.hollandgold.nl/sitemap.xml"]
        elif "thesilvermountain" in domain:
            sitemaps = ["https://www.thesilvermountain.nl/sitemap_products.xml"]
        elif "101munten" in domain:
            sitemaps = ["https://www.101munten.nl/product-sitemap.xml", "https://www.101munten.nl/product-sitemap2.xml"]
        else:
            return None
            
        for sm_url in sitemaps:
            try:
                r = session.get(sm_url, timeout=10)
                if r.status_code == 200:
                    import re
                    urls = re.findall(r'<loc>([^<]+)</loc>', r.text)
                    for u in urls:
                        u_lower = u.lower()
                        # Check of alle keywords in de URL zitten
                        if all(kw in u_lower for kw in keywords):
                            if "1-10" not in u_lower and "1-4" not in u_lower and "1-2" not in u_lower and "tube" not in u_lower and "monsterbox" not in u_lower:
                                print(f"🔧 [Self-Healing] Nieuwe URL gevonden voor {target_label}: {u}")
                                return u
            except Exception:
                pass
    except Exception as e:
        print(f"⚠️ [Self-Healing] Gefaald voor {target_label}: {e}")
    
    return None

def _scrape_price_resilient(session, url_candidates, headers, label="", custom_regex=None, min_price=1.0, max_price=100000.0):
    """
    Probeert meerdere URL's totdat een prijs gevonden wordt.
    Gebruikt 3 extractie-patronen: data-price-amount, JSON-LD, .price class.
    Returns: (prijs, werkende_url) of (None, None)
    """
    for original_url in url_candidates:
        urls_to_try = [original_url]
        attempted_healing = False
        
        while urls_to_try:
            url = urls_to_try.pop(0)
            try:
                r = session.get(url, headers=headers, timeout=8)
                if r.status_code == 404:
                    print(f"⚠️ [{label}] URL 404: {url}")
                    if not attempted_healing:
                        new_url = _resolve_url_from_sitemap(session, url, label)
                        if new_url:
                            urls_to_try.append(new_url)
                        else:
                            print(f"🚨 [FATAL] Zelf-herstel gefaald: Geen URL gevonden voor {label} in sitemap.")
                        attempted_healing = True
                    continue
                if r.status_code != 200:
                    print(f"⚠️ [{label}] HTTP {r.status_code}: {url}")
                    continue
                
                price = None
                
                
                # Check custom regex first
                if custom_regex:
                    for rx in custom_regex:
                        cm_list = re.finditer(rx, r.text, re.IGNORECASE | re.DOTALL)
                        for cm in cm_list:
                            try:
                                price_str = cm.group(1).replace('.', '').replace(',', '.')
                                p = float(price_str)
                                if p >= min_price and p <= max_price:
                                    price = p
                                    break
                            except: pass
                        if price is not None:
                            break
                
                # Patroon 1: woocommerce price tag (TSM / 101M)
                if price is None:
                    m_list = re.finditer(r'woocommerce-Price-amount[^>]*>[^<]*<bdi>.*?([\d.,]+)', r.text)
                    for m in m_list:
                        try:
                            price_str = m.group(1).replace('.', '').replace(',', '.')
                            p = float(price_str)
                            if p >= min_price and p <= max_price:
                                price = p
                                break
                        except: pass
                
                # Patroon 2: data-price-amount (Magento/WooCommerce)
                if price is None:
                    m_list = re.finditer(r'data-price-amount="(\d+\.?\d*)"', r.text)
                    for m in m_list:
                        try:
                            p = float(m.group(1))
                            if p >= min_price and p <= max_price:
                                price = p
                                break
                        except: pass
                
                # Patroon 3: JSON-LD structured data
                if price is None:
                    m_list = re.finditer(r'"price"\s*:\s*"?(\d+[\.,]?\d*)"?', r.text)
                    for m in m_list:
                        try:
                            p = float(m.group(1).replace(',', '.'))
                            if p >= min_price and p <= max_price:
                                price = p
                                break
                        except: pass
                
                # Patroon 4: Generic price class
                if price is None:
                    m_list = re.finditer(r'class="price"[^>]*>€?\s*([\d.,]+)', r.text)
                    for m in m_list:
                        try:
                            price_str = m.group(1).replace('.', '').replace(',', '.')
                            p = float(price_str)
                            if p >= min_price and p <= max_price:
                                price = p
                                break
                        except: pass
                        
                # Patroon 5: Direct € tag (TSM bid fallback)
                if price is None:
                    m_list = re.finditer(r'>\s*€\s*([\d\.,]+)\s*<', r.text)
                    for m in m_list:
                        try:
                            price_str = m.group(1).replace('.', '').replace(',', '.')
                            p = float(price_str)
                            if p >= min_price and p <= max_price:
                                price = p
                                break
                        except: pass
                
                if price and price >= min_price:
                    # Sanity check: verwerp verdachte prijzen (zoals €99.000)
                    if price > 100000.0:
                        print(f"🚨 [{label}] Prijs €{price:.2f} verdacht hoog — overgeslagen")
                        continue 
                    return price, url
                
            except Exception as e:
                print(f"⚠️ [{label}] Error bij {url}: {e}")
                continue
    
    return None, None


def _validate_price(price, expected_spot, metal, label=""):
    """
    Sanity check: verwerp prijs als die >3x of <0.3x expected spot is.
    Returns: True als prijs redelijk is, False als niet.
    """
    if not price or not expected_spot or expected_spot <= 0:
        return False
    ratio = price / expected_spot
    if ratio < 0.3 or ratio > 5.0:
        print(f"🚨 [{label}] Prijs €{price:.2f} is verdacht (ratio {ratio:.1f}x vs spot €{expected_spot:.2f}). Verworpen!")
        return False
    return True


def get_live_holland_gold():
    """
    Live scraper voor Holland Gold (NL) — primaire live dealer.
    Returns: (gold_ask, silver_ask, gold_bar_ask, silver_bar_ask) of (None, None, None, None)
    """
    try:
        from curl_cffi import requests
        session = requests.Session(impersonate="chrome120")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
        }
        
        live_gold_ask, _ = _scrape_price_resilient(session, [
            "https://www.hollandgold.nl/gouden-krugerrand-1-troy-ounce.html",
            "https://www.hollandgold.nl/goud-kopen/gouden-munten/krugerrand-1-troy-ounce.html",
        ], headers, "HG Goud")
        
        live_silv_ask, _ = _scrape_price_resilient(session, [
            "https://www.hollandgold.nl/zilveren-maple-leaf-1-troy-ounce.html",
            "https://www.hollandgold.nl/zilver-kopen/zilveren-munten/maple-leaf-1-troy-ounce.html",
        ], headers, "HG Zilver")
        
        live_gold_bar_ask, _ = _scrape_price_resilient(session, [
            "https://www.hollandgold.nl/goud-kopen/goudbaren-kopen/c-hafner-1-troy-ounce-goud-baar.html",
            "https://www.hollandgold.nl/goud-kopen/goudbaren-kopen/umicore-1-troy-ounce-goudbaar.html",
        ], headers, "HG Goudbaar")
        
        live_silv_bar_ask, _ = _scrape_price_resilient(session, [
            "https://www.hollandgold.nl/zilver-kopen/zilverstaven-kopen/1-kilo-zilverbaar.html",
            "https://www.hollandgold.nl/zilver-kopen/zilverstaven-kopen/umicore-1-kilo-zilverbaar.html",
        ], headers, "HG Zilverbaar")

        if live_gold_ask and live_silv_ask and live_gold_bar_ask:
            print(f"✅ [Live] Holland Gold: Goud €{live_gold_ask:.2f} | Zilver €{live_silv_ask:.2f} | Goudbaar €{live_gold_bar_ask:.2f} | Zilverbaar €{live_silv_bar_ask or '?'}")
            return live_gold_ask, live_silv_ask, live_gold_bar_ask, live_silv_bar_ask
             
    except Exception as e:
        print(f"⚠️ Live Anker (Holland Gold) failed: {e}. Falling back to Pure Algorithm.")
    return None, None, None, None


def get_live_tsm():
    """
    Live scraper voor The Silver Mountain (NL).
    Returns: (silver_munt_ask, gold_ask, gold_bar_ask, silver_bar_ask) of (None, None, None, None)
    """
    try:
        from curl_cffi import requests
        session = requests.Session(impersonate="chrome120")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
        }
        
        silver_munt_ask, _ = _scrape_price_resilient(session, [
            "https://www.thesilvermountain.nl/1-troy-ounce-zilveren-maple-leaf-munt",
            "https://www.thesilvermountain.nl/nl/zilveren-maple-leaf-1-troy-ounce",
            "https://www.thesilvermountain.nl/nl/1-troy-ounce-zilveren-maple-leaf",
        ], headers, "TSM Zilver Munt")
        
        gold_ask, _ = _scrape_price_resilient(session, [
            "https://www.thesilvermountain.nl/1-troy-ounce-gouden-maple-leaf-munt",
            "https://www.thesilvermountain.nl/nl/gouden-maple-leaf-1-troy-ounce",
        ], headers, "TSM Goud Munt")
        
        gold_bar_ask, _ = _scrape_price_resilient(session, [
            "https://www.thesilvermountain.nl/goudbaar-1-troy-ounce-c-hafner",
            "https://www.thesilvermountain.nl/nl/umicore-1-troy-ounce-goudbaar-met-certificaat",
            "https://www.thesilvermountain.nl/nl/goudbaar-1-troy-ounce",
        ], headers, "TSM Goudbaar")
        
        silver_bar_ask, _ = _scrape_price_resilient(session, [
            "https://www.thesilvermountain.nl/1-kilo-zilverbaar",
            "https://www.thesilvermountain.nl/nl/1-kilo-zilverbaar",
        ], headers, "TSM Zilverbaar")
        
        if silver_munt_ask or gold_ask or gold_bar_ask or silver_bar_ask:
            print(f"✅ [Live] TSM: Zilver €{silver_munt_ask or '?'} | Goud €{gold_ask or '?'} | Goudbaar €{gold_bar_ask or '?'} | Zilverbaar €{silver_bar_ask or '?'}")
            return silver_munt_ask, gold_ask, gold_bar_ask, silver_bar_ask
    except Exception as e:
        print(f"⚠️ Live TSM scraper failed: {e}")
    return None, None, None, None


def get_live_101munten():
    """
    Live scraper voor 101 Munten (NL) — WooCommerce.
    Returns: (gold_ask, silver_ask, gold_bar_ask, silver_bar_ask) of (None, None, None, None)
    """
    try:
        from curl_cffi import requests
        session = requests.Session(impersonate="chrome120")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
        }
        
        # Goud
        gold_ask, _ = _scrape_price_resilient(session, [
            "https://www.101munten.nl/product/goud/gouden-munten/gouden-krugerrand-1-oz/"
        ], headers, "101M Goud")
        
        # Zilver
        silver_ask, _ = _scrape_price_resilient(session, [
            "https://www.101munten.nl/product/zilver/zilveren-munten/canadian-maple-leaf/canadian-maple-leaf-1-oz-2025/",
            "https://www.101munten.nl/product/zilver/zilveren-munten/canadian-maple-leaf/1-oz-zilveren-maple-leaf-2024/"
        ], headers, "101M Zilver")
        
        gold_bar_ask, _ = _scrape_price_resilient(session, [
            "https://www.101munten.nl/product/goud/gouden-baren/1-oz/1-oz-gegoten-goudbaar-c-hafner-met-certificaat/",
            "https://www.101munten.nl/product/goud/gouden-baren/1-oz/goudbaar-1-oz-umicore/",
            "https://www.101munten.nl/product/goud/gouden-baren/1-oz/",
        ], headers, "101M Goudbaar")
        
        # Zilverbaar 1kg (101 Munten toont baren EX BTW in hun html class div, dus +21% toevoegen)
        silver_bar_ask, _ = _scrape_price_resilient(session, [
            "https://www.101munten.nl/product/zilver/1-kg-umicore-zilverbaar/"
        ], headers, "101M Zilverbaar")
        if silver_bar_ask:
            silver_bar_ask = round(silver_bar_ask * 1.21, 2)
        
        if gold_ask or silver_ask or gold_bar_ask or silver_bar_ask:
            print(f"✅ [Live] 101 Munten: Goud €{gold_ask or '?'} | Zilver €{silver_ask or '?'} | Goudbaar €{gold_bar_ask or '?'} | Zilverbaar €{silver_bar_ask or '?'}")
            return gold_ask, silver_ask, gold_bar_ask, silver_bar_ask
    except Exception as e:
        print(f"⚠️ Live 101 Munten scraper failed: {e}")
    return None, None, None, None


# ============================================================
# LIVE BID (INKOOP) SCRAPERS
# ============================================================

async def get_live_bid_holland_gold():
    """
    Live inkoop-scraper voor Holland Gold via headless browser (Playwright),
    omdat bid-prijzen via JS-formules dynamisch in de browser berekend worden
    (ze zitten niet in de broncode of onbeschermde API requests).
    """
    try:
        from playwright.async_api import async_playwright
        import re
        
        gold_bid = None
        silv_bid = None
        gold_bar_bid = None
        silv_bar_bid = None

        async with async_playwright() as p:
            b = await p.chromium.launch(headless=True)
            page = await b.new_page()
            
            # 1. Gouden Munten
            try:
                await page.goto('https://www.hollandgold.nl/verkopen/gouden-munten.html', wait_until='networkidle', timeout=15000)
                await page.wait_for_timeout(2000)
                els = page.locator("text='Krugerrand 1 troy ounce gouden munt - diverse jaartallen'")
                if await els.count() > 0:
                    row = els.nth(0).locator("xpath=ancestor::div[contains(@class, 'berekenwaarde__leftpane__products__product')]").first
                    txt = await row.inner_text()
                    txt = txt.replace('\n', '').replace('\r', '')
                    m = re.search(r'€\s*([\d\.,\s]+)', txt)
                    if m: gold_bid = float(m.group(1).replace('.', '').replace(',', '.').replace(' ', ''))
            except Exception as e:
                print(f"⚠️ HG Playwright Goud Munt failed: {e}")
                
            # 2. Zilveren Munten
            try:
                await page.goto('https://www.hollandgold.nl/verkopen/zilveren-munten.html', wait_until='networkidle', timeout=15000)
                await page.wait_for_timeout(1500)
                els = page.locator("text='Maple Leaf 1 troy ounce zilveren munt - diverse jaartallen'")
                if await els.count() > 0:
                    row = els.nth(0).locator("xpath=ancestor::div[contains(@class, 'berekenwaarde__leftpane__products__product')]").first
                    txt = await row.inner_text()
                    txt = txt.replace('\n', '').replace('\r', '')
                    m = re.search(r'€\s*([\d\.,\s]+)', txt)
                    if m: silv_bid = float(m.group(1).replace('.', '').replace(',', '.').replace(' ', ''))
            except Exception: pass
                
            # 3. Goudbaren
            try:
                await page.goto('https://www.hollandgold.nl/verkopen/goudbaren.html', wait_until='networkidle', timeout=15000)
                await page.wait_for_timeout(1500)
                for lbl in ['C. Hafner 1 troy ounce goudbaar', 'Heraeus 1 troy ounce goudbaar', 'Valcambi SA 1 troy ounce goudbaar']:
                    els = page.locator(f"text='{lbl}'")
                    if await els.count() > 0:
                        row = els.nth(0).locator("xpath=ancestor::div[contains(@class, 'berekenwaarde__leftpane__products__product')]").first
                        txt = await row.inner_text()
                        txt = txt.replace('\n', '').replace('\r', '')
                        m = re.search(r'€\s*([\d\.,\s]+)', txt)
                        if m: 
                            gold_bar_bid = float(m.group(1).replace('.', '').replace(',', '.').replace(' ', ''))
                            break
            except Exception: pass
                
            # 4. Zilverbaren 1kg
            try:
                await page.goto('https://www.hollandgold.nl/verkopen/zilverbaren.html', wait_until='networkidle', timeout=15000)
                await page.wait_for_timeout(1500)
                for lbl in ['Heraeus 1 kilogram zilverbaar', 'Umicore 1 kilogram zilverbaar']:
                    els = page.locator(f"text='{lbl}'")
                    if await els.count() > 0:
                        row = els.nth(0).locator("xpath=ancestor::div[contains(@class, 'berekenwaarde__leftpane__products__product')]").first
                        txt = await row.inner_text()
                        txt = txt.replace('\n', '').replace('\r', '')
                        m = re.search(r'€\s*([\d\.,\s]+)', txt)
                        if m: 
                            silv_bar_bid = float(m.group(1).replace('.', '').replace(',', '.').replace(' ', ''))
                            break
            except Exception: pass
            
            await b.close()
            return gold_bid, silv_bid, gold_bar_bid, silv_bar_bid
            
    except ImportError:
        print("⚠️ Playwright niet geïnstalleerd. Zorg dat je 'playwright' hebt via pip.")
    except Exception as e:
        print(f"⚠️ Live bid HG Playwright generiek gefaald: {e}")
        
    return None, None, None, None

def get_live_bid_tsm():
    """
    Live scraper voor inkoopprijzen The Silver Mountain (Inkoop Edelmetaal).
    Gebruikt stricte regex patronen om de header scrap-gold tickers te omzeilen.
    """
    try:
        from curl_cffi import requests
        session = requests.Session(impersonate="chrome120")
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}
        
        # Regex specifiek voor inkoopedelmetaal (vermijd de kleine scrap prijzen in navigatie)
        bid_patterns = [
            r'class=\"[^\"]*price[^\"]*\"[^>]*>\s*€\s*([\d.,]+)',
            r'>\s*€\s*([\d\.,]+)\s*<'
        ]
        
        gold_bid, _ = _scrape_price_resilient(session, [
            "https://www.inkoopedelmetaal.nl/goud-verkopen/gouden-munten/krugerrand",
            "https://www.inkoopedelmetaal.nl/1-troy-ounce-gouden-maple-leaf-munt"
        ], headers, "TSM Goud Inkoop", bid_patterns, min_price=1000.0)
        
        silv_bid, _ = _scrape_price_resilient(session, [
            "https://www.inkoopedelmetaal.nl/zilver-verkopen/zilveren-munten/maple-leaf",
            "https://www.inkoopedelmetaal.nl/1-troy-ounce-zilver-maple-leaf-munt"
        ], headers, "TSM Zilver Inkoop", bid_patterns, min_price=15.0, max_price=60.0)
        
        gold_bar_bid, _ = _scrape_price_resilient(session, [
            "https://www.inkoopedelmetaal.nl/goud-verkopen/goudbaren/1-troy-ounce"
        ], headers, "TSM Goudbaar Inkoop", bid_patterns, min_price=1000.0)
        
        silv_bar_bid, _ = _scrape_price_resilient(session, [
            "https://www.inkoopedelmetaal.nl/zilver-verkopen/zilverbaren/1-kilogram",
            "https://www.inkoopedelmetaal.nl/1-kilo-zilverbaar"
        ], headers, "TSM Zilverbaar Inkoop", bid_patterns, min_price=400.0)
        
        return gold_bid, silv_bid, gold_bar_bid, silv_bar_bid
    except Exception as e:
        print(f"⚠️ Live bid TSM failed: {e}")
    return None, None, None, None


# ============================================================
# TARGETED SCRAPER (Apples with Apples)
# ============================================================
async def get_highest_live_bid_for_item(pre_scan_data, spot_prices):
    """
    Zoekt de actuele, live Inkoopprijs (Bid) voor een specifiek product (pre_scan_data).
    Gebaseerd op de dealer index (Apple to Apple match) en live scrapers.
    Als live scraping faalt of niet ondersteund is voor deze specifieke munt,
    valt hij terug op het algoritmische bod via de DELEAR_PROFILES matrix.
    """
    highest_bid = 0.0
    best_dealer = "Onbekend"
    
    # 1. LIVE SCRAPE: TSM Inkoop
    tsm_urls = _find_urls("TSM Inkoop", pre_scan_data, [])
    live_price = None
    if tsm_urls:
        try:
            from curl_cffi import requests
            session = requests.Session(impersonate="chrome120")
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}
            bid_patterns = [
                r'class=\"[^\"]*price[^\"]*\"[^>]*>\s*€\s*([\d.,]+)',
                r'>\s*€\s*([\d\.,]+)\s*<'
            ]
            live_price, _ = _scrape_price_resilient(session, tsm_urls, headers, "TSM Live Inkoop", bid_patterns, min_price=10.0)
            if live_price and live_price > highest_bid:
                highest_bid = live_price
                best_dealer = "The Silver Mountain"
        except Exception as e:
            print(f"⚠️ Live bid TSM inkoop gefaald: {e}")
            
    # 2. ALGORITMISCHE FALLBACKS (Voor andere dealers)
    category = _determine_product_category(pre_scan_data)
    try:
        gewicht_oz = float(pre_scan_data.get("gewicht_oz", 1.0))
    except:
        gewicht_oz = 1.0
        
    metaal = str(pre_scan_data.get("metaal", "Goud")).lower()
    ref_spot = spot_prices.get("gold_eur_oz_physical", 0) if "goud" in metaal else spot_prices.get("silver_eur_oz_physical", 0)
    int_waarde = ref_spot * gewicht_oz
    
    for dp in DEALER_PROFILES:
        if dp["name"] == "Inkoop Edelmetaal": continue
        bid_margin = dp["bid_premiums"].get(category)
        if bid_margin is not None:
            algo_bid = int_waarde * (1 + (bid_margin / 100))
            if algo_bid > highest_bid:
                if live_price is None or algo_bid > live_price:
                    highest_bid = algo_bid
                    best_dealer = dp["name"]
                   
    return round(highest_bid, 2), best_dealer


def get_specific_dealer_ask(dealer_name, pre_scan_data):
    """
    Gebruikt de Nachtelijke index (dealer_urls.json) om exact het geuploade product 
    te vinden bij een specifieke dealer.
    """
    if not pre_scan_data: return None
    
    urls = _find_urls(dealer_name, pre_scan_data, [])
    if not urls: return None
    
    try:
        from curl_cffi import requests
        session = requests.Session(impersonate="chrome120")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
        }
        
        # 101 Munten extra BTW check
        is_101m_silver_bar = False
        if dealer_name == "101 Munten":
            metal = pre_scan_data.get("metaal", "unknown").lower()
            ptype = pre_scan_data.get("type", "unknown").lower()
            if "zilver" in metal and "baar" in ptype:
                 is_101m_silver_bar = True
                 
        price, _ = _scrape_price_resilient(session, urls, headers, f"{dealer_name} Specifiek")
        
        if price and is_101m_silver_bar:
             price = round(price * 1.21, 2)
             
        return price
    except Exception as e:
        print(f"⚠️ Specifieke scrape voor {dealer_name} gefaald: {e}")
        return None

# ============================================================
# MAIN DEALER DATA FETCH
# ============================================================

async def fetch_dealer_premiums(pre_scan_data=None):
    """
    Haalt premies (ask/bid) op van gerenommeerde edelmetaaldealers.
    HYBRIDE STRATEGIE: 
    1. Live scrape Holland Gold + The Silver Mountain als ankerprijzen
    2. Bereken overige dealers algoritmisch per productcategorie
    """
    
    # 1. Haal live spotprijs op
    live_spot = get_live_spot_prices()
    spot_gold = live_spot['gold_eur_oz_physical']
    spot_silver = live_spot['silver_eur_oz_physical']
    
    if not spot_gold or spot_gold == 0: spot_gold = 2750.0  
    if not spot_silver or spot_silver == 0: spot_silver = 30.0
    
    # 2. Bepaal productcategorie
    product_cat = _determine_product_category(pre_scan_data)
    
    # 3. Live scrapers
    hg_live_gold, hg_live_silv, hg_live_gold_bar, hg_live_silv_bar = get_live_holland_gold()
    is_live_hg = bool(hg_live_gold and hg_live_silv and hg_live_gold_bar)
    
    hg_bid_gold, hg_bid_silv, hg_bid_gold_bar, hg_bid_silv_bar = await get_live_bid_holland_gold()
    
    tsm_silv_munt, tsm_gold_munt, tsm_gold_bar, tsm_silv_bar = get_live_tsm()
    tsm_bid_gold, tsm_bid_silv, tsm_bid_gold_bar, tsm_bid_silv_bar = get_live_bid_tsm()
    is_live_tsm = bool(tsm_silv_munt or tsm_gold_munt or tsm_gold_bar or tsm_silv_bar)
    
    m101_gold, m101_silver, m101_gold_bar, m101_silv_bar = get_live_101munten()
    is_live_101 = bool(m101_gold or m101_silver or m101_gold_bar or m101_silv_bar)
    
    # 4. Parse dynamic variables from Pass 1
    target_weight = 1.0
    target_metal = "goud"
    target_type = "munt"
    if pre_scan_data:
        try:
            target_weight = float(pre_scan_data.get("gewicht_oz", 1.0))
        except:
            target_weight = 1.0
        target_metal = pre_scan_data.get("metaal", "goud").lower()
        target_type = pre_scan_data.get("type", "munt").lower()
    
    base_spot = spot_gold if "goud" in target_metal else spot_silver
    if "platina" in target_metal: base_spot = spot_gold * 0.4
    
    # Gewicht premium modifier
    weight_premium_modifier = 0.0
    if target_weight <= 0.1: weight_premium_modifier = 15.0
    elif target_weight <= 0.25: weight_premium_modifier = 9.0
    elif target_weight <= 0.5: weight_premium_modifier = 4.5
    elif target_weight >= 10.0: weight_premium_modifier = -1.5
    elif target_weight >= 32.0: weight_premium_modifier = -2.5
    
    dealer_data = {
        "Maple Leaf Zilver (1 Oz)": [],
        "Krugerrand Goud (1 Oz)": [],
        "Goudbaar (1 Oz)": [],
        "Zilverbaar (1kg)": [],
        "Geanalyseerd Product": []
    }
    
    # 5. Holland Gold Live Insert
    if is_live_hg:
        dealer_data["Krugerrand Goud (1 Oz)"].append({
            "dealer_name": "Holland Gold", "country": "NL", 
            "ask_price": hg_live_gold, "bid_price": hg_bid_gold or (round(spot_gold * 0.988, 2) if spot_gold else None), 
            "method": "LIVE_SCRAPE", "bid_source": "LIVE" if hg_bid_gold else "ALGO"
        })
        dealer_data["Maple Leaf Zilver (1 Oz)"].append({
            "dealer_name": "Holland Gold", "country": "NL", 
            "ask_price": hg_live_silv, "bid_price": hg_bid_silv or (round(spot_silver * 0.97, 2) if spot_silver else None), 
            "method": "LIVE_SCRAPE", "bid_source": "LIVE" if hg_bid_silv else "ALGO"
        })
        dealer_data["Goudbaar (1 Oz)"].append({
            "dealer_name": "Holland Gold", "country": "NL", 
            "ask_price": hg_live_gold_bar, "bid_price": hg_bid_gold_bar or (round(spot_gold * 0.99, 2) if spot_gold else None), 
            "method": "LIVE_SCRAPE", "bid_source": "LIVE" if hg_bid_gold_bar else "ALGO"
        })
        if hg_live_silv_bar:
            dealer_data["Zilverbaar (1kg)"].append({
                "dealer_name": "Holland Gold", "country": "NL", 
                "ask_price": hg_live_silv_bar, "bid_price": hg_bid_silv_bar or (round(spot_silver * 0.93 * 32.15, 2) if spot_silver else None), 
                "method": "LIVE_SCRAPE", "bid_source": "LIVE" if hg_bid_silv_bar else "ALGO"
            })
        # Geanalyseerd Product (live derived of specifiek)
        hg_dyn = get_specific_dealer_ask("Holland Gold", pre_scan_data)
        if hg_dyn:
            dyn_ask_hg = hg_dyn
            hg_method = "APPLES_TO_APPLES"
        else:
            hg_method = "LIVE_DERIVED"
            if "goud" in target_metal:
                hg_base = hg_live_gold_bar if "baar" in target_type else hg_live_gold
                hg_per_oz = hg_base  # prijs per oz
                dyn_ask_hg = hg_per_oz * target_weight if hg_per_oz else None
            else:
                hg_per_oz = hg_live_silv
                dyn_ask_hg = hg_per_oz * target_weight if hg_per_oz else None
        
        dealer_data["Geanalyseerd Product"].append({
            "dealer_name": "Holland Gold", "country": "NL",
            "ask_price": round(dyn_ask_hg, 2) if dyn_ask_hg else None,
            "bid_price": round(base_spot * target_weight * 0.97, 2) if base_spot else None,
            "method": hg_method
        })
    
    # 6. TSM Live Insert
    if is_live_tsm:
        if tsm_gold_munt:
            dealer_data["Krugerrand Goud (1 Oz)"].append({
                "dealer_name": "The Silver Mountain", "country": "NL", 
                "ask_price": tsm_gold_munt, "bid_price": tsm_bid_gold or (round(spot_gold * 0.99, 2) if spot_gold else None),
                "method": "LIVE_SCRAPE", "bid_source": "LIVE" if tsm_bid_gold else "ALGO"
            })
        if tsm_silv_munt:
            dealer_data["Maple Leaf Zilver (1 Oz)"].append({
                "dealer_name": "The Silver Mountain", "country": "NL", 
                "ask_price": tsm_silv_munt, "bid_price": tsm_bid_silv or (round(spot_silver * 0.97, 2) if spot_silver else None),
                "method": "LIVE_SCRAPE", "bid_source": "LIVE" if tsm_bid_silv else "ALGO"
            })
        if tsm_gold_bar:
            dealer_data["Goudbaar (1 Oz)"].append({
                "dealer_name": "The Silver Mountain", "country": "NL", 
                "ask_price": tsm_gold_bar, "bid_price": tsm_bid_gold_bar or (round(spot_gold * 0.992, 2) if spot_gold else None),
                "method": "LIVE_SCRAPE", "bid_source": "LIVE" if tsm_bid_gold_bar else "ALGO"
            })
        if tsm_silv_bar:
            dealer_data["Zilverbaar (1kg)"].append({
                "dealer_name": "The Silver Mountain", "country": "NL", 
                "ask_price": tsm_silv_bar, "bid_price": tsm_bid_silv_bar or (round(spot_silver * 32.15 * 0.96, 2) if spot_silver else None),
                "method": "LIVE_SCRAPE", "bid_source": "LIVE" if tsm_bid_silv_bar else "ALGO"
            })
        
        tsm_dyn = get_specific_dealer_ask("The Silver Mountain", pre_scan_data)
        if tsm_dyn:
            dealer_data["Geanalyseerd Product"].append({
                "dealer_name": "The Silver Mountain", "country": "NL",
                "ask_price": round(tsm_dyn, 2),
                "bid_price": round(base_spot * target_weight * 0.97, 2) if base_spot else None,
                "method": "APPLES_TO_APPLES"
            })
        elif "goud" in target_metal and (tsm_gold_bar or tsm_gold_munt):
            tsm_base = tsm_gold_bar if "baar" in target_type and tsm_gold_bar else tsm_gold_munt
            tsm_bid_base = tsm_bid_gold_bar if "baar" in target_type and tsm_bid_gold_bar else tsm_bid_gold
            if tsm_base:
                dealer_data["Geanalyseerd Product"].append({
                    "dealer_name": "The Silver Mountain", "country": "NL",
                    "ask_price": round(tsm_base * target_weight, 2),
                    "bid_price": round(tsm_bid_base * target_weight, 2) if tsm_bid_base else (round(base_spot * target_weight * 0.97, 2) if base_spot else None),
                    "method": "LIVE_DERIVED"
                })
        elif "zilver" in target_metal and tsm_silv_munt:
            tsm_base = tsm_silv_munt
            dealer_data["Geanalyseerd Product"].append({
                "dealer_name": "The Silver Mountain", "country": "NL",
                "ask_price": round(tsm_base * target_weight, 2),
                "bid_price": round(tsm_bid_silv * target_weight, 2) if tsm_bid_silv else (round(base_spot * target_weight * 0.97, 2) if base_spot else None),
                "method": "LIVE_DERIVED"
            })
    
    # 7. 101 Munten Live Insert
    if is_live_101:
        if m101_gold:
            dealer_data["Krugerrand Goud (1 Oz)"].append({
                "dealer_name": "101 Munten", "country": "NL",
                "ask_price": m101_gold, "bid_price": round(spot_gold * 0.98, 2) if spot_gold else None,
                "method": "LIVE_SCRAPE"
            })
        if m101_silver:
            dealer_data["Maple Leaf Zilver (1 Oz)"].append({
                "dealer_name": "101 Munten", "country": "NL",
                "ask_price": m101_silver, "bid_price": round(spot_silver * 0.96, 2) if spot_silver else None,
                "method": "LIVE_SCRAPE"
            })
        if m101_gold_bar:
            dealer_data["Goudbaar (1 Oz)"].append({
                "dealer_name": "101 Munten", "country": "NL",
                "ask_price": m101_gold_bar, "bid_price": round(spot_gold * 0.99, 2) if spot_gold else None,
                "method": "LIVE_SCRAPE"
            })
        if m101_silv_bar:
            dealer_data["Zilverbaar (1kg)"].append({
                "dealer_name": "101 Munten", "country": "NL",
                "ask_price": m101_silv_bar, "bid_price": round(spot_silver * 32.15 * 0.96, 2) if spot_silver else None,
                "method": "LIVE_SCRAPE"
            })
        # 101M Geanalyseerd Product
        m101_dyn = get_specific_dealer_ask("101 Munten", pre_scan_data)
        if m101_dyn:
            m101_base_calculated = m101_dyn
            m101_method = "APPLES_TO_APPLES"
        else:
            m101_method = "LIVE_DERIVED"
            if "goud" in target_metal and m101_gold:
                m101_base = m101_gold
            elif m101_silver:
                m101_base = m101_silver
            else:
                m101_base = None
            m101_base_calculated = m101_base * target_weight if m101_base else None
                
        if m101_base_calculated:
            dealer_data["Geanalyseerd Product"].append({
                "dealer_name": "101 Munten", "country": "NL",
                "ask_price": round(m101_base_calculated, 2),
                "bid_price": round(base_spot * target_weight * 0.96, 2) if base_spot else None,
                "method": m101_method
            })
    
    # 8. Algoritmische dealer berekeningen (per productcategorie)
    algo_dealers = DEALER_PROFILES.copy()
    
    # Voeg Holland Gold toe als algo als live faalt
    if not is_live_hg:
        algo_dealers.append({
            "name": "Holland Gold", "country": "NL",
            "ask_premiums": {"goud_munt": 4.0, "goud_baar": 2.8, "zilver_munt": 20.0, "zilver_baar": 15.0, "zilver_collectible": 26.0},
            "bid_premiums": {"goud_munt": -1.2, "goud_baar": -1.0, "zilver_munt": -3.0, "zilver_baar": -4.0, "zilver_collectible": -5.0},
        })
    
    # Filter live dealers uit algo
    if is_live_tsm:
        algo_dealers = [d for d in algo_dealers if d["name"] != "The Silver Mountain"]
    if is_live_101:
        algo_dealers = [d for d in algo_dealers if d["name"] != "101 Munten"]
    
    for dealer in algo_dealers:
        var_ask = random.uniform(-0.3, 0.3)  # Iets meer variatie
        var_bid = random.uniform(-0.2, 0.2)
        
        ask_premiums = dealer.get("ask_premiums", {})
        if not isinstance(ask_premiums, dict): ask_premiums = {}
        bid_premiums = dealer.get("bid_premiums", {})
        if not isinstance(bid_premiums, dict): bid_premiums = {}
        is_sell_only = dealer.get("sell_only", False)
        
        # Zilver (1 Oz Munt)
        sil_munt_ask_pct = ask_premiums.get("zilver_munt", 20.0) + var_ask
        sil_munt_bid_pct = bid_premiums.get("zilver_munt", -3.0) + var_bid
        
        if not is_sell_only:
            dealer_data["Maple Leaf Zilver (1 Oz)"].append({
                "dealer_name": dealer["name"], "country": dealer["country"],
                "ask_price": round(spot_silver * (1 + sil_munt_ask_pct/100), 2) if spot_silver else None,
                "bid_price": round(spot_silver * (1 + sil_munt_bid_pct/100), 2) if spot_silver else None,
                "method": "ALGORITME"
            })
        else:
            # Alleen bid voor sell_only dealers
            dealer_data["Maple Leaf Zilver (1 Oz)"].append({
                "dealer_name": dealer["name"], "country": dealer["country"],
                "ask_price": float('inf'),  # Nooit laagste ask
                "bid_price": round(spot_silver * (1 + sil_munt_bid_pct/100), 2) if spot_silver else None,
                "method": "ALGORITME"
            })
        
        # Goud Munt (1 Oz Krugerrand)
        gld_munt_ask_pct = ask_premiums.get("goud_munt", 4.0) + var_ask
        gld_munt_bid_pct = bid_premiums.get("goud_munt", -1.0) + var_bid
        
        if not is_sell_only:
            dealer_data["Krugerrand Goud (1 Oz)"].append({
                "dealer_name": dealer["name"], "country": dealer["country"],
                "ask_price": round(spot_gold * (1 + gld_munt_ask_pct/100), 2) if spot_gold else None,
                "bid_price": round(spot_gold * (1 + gld_munt_bid_pct/100), 2) if spot_gold else None,
                "method": "ALGORITME"
            })
        else:
            dealer_data["Krugerrand Goud (1 Oz)"].append({
                "dealer_name": dealer["name"], "country": dealer["country"],
                "ask_price": float('inf'),
                "bid_price": round(spot_gold * (1 + gld_munt_bid_pct/100), 2) if spot_gold else None,
                "method": "ALGORITME"
            })
        
        # Goudbaar (1 Oz)
        gld_bar_ask_pct = ask_premiums.get("goud_baar", 2.5) + var_ask
        gld_bar_bid_pct = bid_premiums.get("goud_baar", -1.0) + var_bid
        
        if not is_sell_only:
            dealer_data["Goudbaar (1 Oz)"].append({
                "dealer_name": dealer["name"], "country": dealer["country"],
                "ask_price": round(spot_gold * (1 + gld_bar_ask_pct/100), 2) if spot_gold else None,
                "bid_price": round(spot_gold * (1 + gld_bar_bid_pct/100), 2) if spot_gold else None,
                "method": "ALGORITME"
            })
        else:
            dealer_data["Goudbaar (1 Oz)"].append({
                "dealer_name": dealer["name"], "country": dealer["country"],
                "ask_price": float('inf'),
                "bid_price": round(spot_gold * (1 + gld_bar_bid_pct/100), 2) if spot_gold else None,
                "method": "ALGORITME"
            })
        
        # Geanalyseerd Product (dynamisch per categorie)
        dyn_ask_pct = ask_premiums.get(product_cat, 4.0) + weight_premium_modifier + var_ask
        dyn_bid_pct = bid_premiums.get(product_cat, -1.0) + var_bid
        
        dyn_spot = base_spot * target_weight if base_spot else None
        
        if not is_sell_only:
            dealer_data["Geanalyseerd Product"].append({
                "dealer_name": dealer["name"], "country": dealer["country"],
                "ask_price": round(dyn_spot * (1 + dyn_ask_pct/100), 2) if dyn_spot else None,
                "bid_price": round(dyn_spot * (1 + dyn_bid_pct/100), 2) if dyn_spot else None,
                "method": "ALGORITME"
            })
        else:
            dealer_data["Geanalyseerd Product"].append({
                "dealer_name": dealer["name"], "country": dealer["country"],
                "ask_price": float('inf'),
                "bid_price": round(dyn_spot * (1 + dyn_bid_pct/100), 2) if dyn_spot else None,
                "method": "ALGORITME"
            })
        
    return dealer_data


# ============================================================
# PRICE LOOKUP HELPERS
# ============================================================

def get_highest_bid_price(item_name, dealers_data):
    """Pakt de allerhoogste inkoopprijs (bid) van alle dealers."""
    if item_name not in dealers_data:
        return 0.0, "", "", ""
        
    highest_bid = 0.0
    best_dealer = ""
    best_country = ""
    best_method = ""
    
    for dealer in dealers_data[item_name]:
        if dealer["bid_price"] > highest_bid:
            highest_bid = dealer["bid_price"]
            best_dealer = dealer["dealer_name"]
            best_country = dealer["country"]
            best_method = dealer.get("method", "ALGORITME")
            
    return highest_bid, best_dealer, best_country, best_method


def get_lowest_ask_price(item_name, dealers_data):
    """Pakt de allerlaagste verkoopprijs (ask) van alle dealers."""
    if item_name not in dealers_data:
        return 0.0, "", "", ""
        
    lowest_ask = float('inf')
    best_dealer = ""
    best_country = ""
    best_method = ""
    
    for dealer in dealers_data[item_name]:
        if dealer["ask_price"] < lowest_ask:
            lowest_ask = dealer["ask_price"]
            best_dealer = dealer["dealer_name"]
            best_country = dealer["country"]
            best_method = dealer.get("method", "ALGORITME")
            
    if lowest_ask == float('inf'):
        return 0.0, "", "", ""
        
    return lowest_ask, best_dealer, best_country, best_method


_SHIPPING_LOOKUP = {d["name"]: d.get("shipping_nl", 0) for d in DEALER_PROFILES}

def get_top_3_ask(item_name, dealers_data):
    """
    Retourneert de top-3 goedkoopste dealers (ask + verzending) voor een product.
    Returns: list of (prijs, dealer_naam, land, methode, verzendkosten)
    """
    if item_name not in dealers_data:
        return []
    
    valid_dealers = [d for d in dealers_data[item_name] if d["ask_price"] < float('inf')]
    # Sorteer op totaalprijs (ask + verzending naar NL)
    sorted_dealers = sorted(valid_dealers, key=lambda d: d["ask_price"] + _SHIPPING_LOOKUP.get(d["dealer_name"], 0))
    
    top3 = []
    for d in sorted_dealers[:3]:
        shipping = _SHIPPING_LOOKUP.get(d["dealer_name"], 0)
        top3.append((d["ask_price"], d["dealer_name"], d["country"], d.get("method", "ALGORITME"), shipping))
    
    return top3

async def get_cached_dealer_premiums(pre_scan_data=None, max_age_seconds=14400):
    """
    Smart On-Demand Lazy Load Cache voor dealers.
    Haalt de dealer_data op via SQLite database cache, in plaats van RAM, voor persisterende snelheid.
    """
    # Maak een simpele key op basis van de input
    metal = "goud"
    ptype = "munt"
    oz = 1.0
    if pre_scan_data:
        metal = pre_scan_data.get("metaal", "goud")
        ptype = pre_scan_data.get("type", "munt")
        try:
            oz = float(pre_scan_data.get("gewicht_oz", 1.0))
        except:
            oz = 1.0
            
    cache_key = f"{metal}_{ptype}_{oz}"
    now = time.time()
    
    # Check SQLite cache status
    cached_json, cached_time = get_price_cache(cache_key)
    if cached_json and cached_time:
        if now - cached_time < max_age_seconds:
            print(f"⚡ [Cache HIT] Dealerdata voor `{cache_key}` laadt in ({(now - cached_time)/3600:.1f}u oud).")
            try:
                return json.loads(cached_json)
            except Exception as e:
                print(f"⚠️ [Cache ERROR] JSON parse fail voor `{cache_key}` ({e}). Scrapen...")
                pass
            
    print(f"🐢 [Cache MISS] Dealerdata voor `{cache_key}` wordt Live opgehaald...")
    live_data = await fetch_dealer_premiums(pre_scan_data)
    
    # Sla resultaat op in SQLite
    if live_data:
        set_price_cache(cache_key, json.dumps(live_data), now)
    
    return live_data


def get_top_3_bid(item_name, dealers_data):
    """
    FIX B: Retourneert de top-3 beste inkopers (bid) voor een product.
    Returns: list of (prijs, dealer_naam, land, methode)
    """
    if item_name not in dealers_data:
        return []
    
    sorted_dealers = sorted(dealers_data[item_name], key=lambda d: d["bid_price"], reverse=True)
    
    top3 = []
    top3 = []
    for d in sorted_dealers[:3]:
        top3.append((d["bid_price"], d["dealer_name"], d["country"], d.get("method", "ALGORITME")))
    
    return top3

async def calibrate_dealer_premiums(spot_prices):
    """
    [Zelflerend Algoritme]
    Haalt de échte inkoopprijs op bij The Silver Mountain voor 3 benchmark producten,
    berekent de actuele "premium boven/onder spot", en overschrijft de hardcoded 
    `bid_premiums` in de in-memory DEALER_PROFILES.
    Andere dealers worden hieraan gerelateerd (bijv. GWK is vaak iets slechter dan TSM).
    """
    global DEALER_PROFILES
    print("🤖 [Auto-Kalibratie] Starten van dynamische buy-back premium kalibratie...")
    
    # 1. Benchmarks definiëren (op verzoek van gebruiker)
    benchmarks = {
        "goud_munt":   {"metaal": "goud", "type": "munt", "gewicht_oz": 1.0, "merk_of_muntnaam": "krugerrand"},
        "goud_baar":   {"metaal": "goud", "type": "baar", "gewicht_oz": 1.0, "merk_of_muntnaam": "hafner"},
        "zilver_munt": {"metaal": "zilver", "type": "munt", "gewicht_oz": 1.0, "merk_of_muntnaam": "maple leaf"},
        "zilver_baar": {"metaal": "zilver", "type": "baar", "gewicht_oz": 32.15, "merk_of_muntnaam": "cook island"}
    }
    
    spot_ag = spot_prices.get("silver_eur_oz_paper", 0)
    spot_au = spot_prices.get("gold_eur_oz_paper", 0)
    
    if not spot_ag or not spot_au:
        print("⚠️ [Auto-Kalibratie] Geen geldige spotprijzen gevonden. Kalibratie geannuleerd.")
        return False
        
    new_premiums = {}
    
    # 2. Scrape TSM Inkoop voor de benchmarks
    for cat, pre_scan_data in benchmarks.items():
        base_spot = spot_ag if "zilver" in cat else spot_au
        gewicht = pre_scan_data["gewicht_oz"]
        ruwe_waarde = base_spot * gewicht
        
        urls = _find_urls("TSM Inkoop", pre_scan_data, [])
        if urls:
            try:
                from curl_cffi import requests as c_requests
                session = c_requests.Session(impersonate="chrome120")
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}
                bid_patterns = [r'class=\"[^\"]*price[^\"]*\"[^>]*>\s*€\s*([\d.,]+)', r'>\s*€\s*([\d\.,]+)\s*<']
                live_bid, _ = _scrape_price_resilient(session, urls, headers, f"TSM Kalibratie {cat}", bid_patterns, min_price=10.0)
                
                if live_bid and live_bid > 0:
                    premium_pct = ((live_bid - ruwe_waarde) / ruwe_waarde) * 100
                    new_premiums[cat] = round(premium_pct, 1)
                    print(f"✅ [Kalibratie] {cat}: TSM koopt in voor €{live_bid:.2f} (Spot: €{ruwe_waarde:.2f}) -> {premium_pct:+.1f}%")
                else:
                    print(f"⚠️ [Kalibratie] Kon geen prijs scrapen voor {cat}. Behoudt oude waarde.")
            except Exception as e:
                print(f"⚠️ [Kalibratie] Fout bij scrapen {cat}: {e}")
                
    # 3. Update DEALER_PROFILES als we succesvol TSM hebben gekalibreerd
    if not new_premiums:
        print("⚠️ [Auto-Kalibratie] Kalibratie mislukt voor alle benchmarks.")
        return False
        
    for dp in DEALER_PROFILES:
        # Als TSM is gekalibreerd, pas andere dealers relatief aan
        for cat, tsm_premium in new_premiums.items():
            if cat in dp.get("bid_premiums", {}):
                # Relatieve offsets t.o.v. TSM bepalen op basis van originele verhoudingen
                offset = 0.0
                if dp["name"] == "The Silver Mountain": 
                    offset = 0.0
                elif dp["name"] == "Goudwisselkantoor": 
                    offset = -2.0 if "zilver" in cat else -0.5
                elif dp["name"] == "Goudonline.nl": 
                    offset = -2.0 if "zilver" in cat else -0.4
                elif dp["name"] == "101 Munten": 
                    offset = -3.0 if "zilver" in cat else -0.7
                elif dp["name"] == "Goud999": 
                    offset = -1.0 if "zilver" in cat else -0.1
                
                new_margin = round(tsm_premium + offset, 1)
                dp["bid_premiums"][cat] = new_margin
                
                # Als zilver_munt is geüpdatet, update ook collectible (+3% standaard extra)
                if cat == "zilver_munt" and "zilver_collectible" in dp.get("bid_premiums", {}):
                    dp["bid_premiums"]["zilver_collectible"] = round(new_margin + 3.0, 1)
                    
    print(f"🎯 [Auto-Kalibratie] DEALER_PROFILES succesvol geüpdatet: {new_premiums}")
    return True
