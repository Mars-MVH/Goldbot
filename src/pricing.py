import yfinance as yf
import pandas as pd
import traceback
import os
import requests
import time

# 1 Troy Ounce in Grams
TROY_OUNCE_GRAMS = 31.1034768

# Cache voor fallback prijzen (voorkomt onnodige API calls)
_price_cache = {"gold_eur": 0.0, "silver_eur": 0.0, "timestamp": 0, "source": "none"}

def _fetch_metals_api():
    """
    Fallback 1: Metals-API (metals-api.com)
    Gratis: 100 calls/maand. Retourneert goud/zilver in EUR.
    """
    api_key = os.environ.get("METALS_API_KEY", "")
    if not api_key:
        return None, None
    
    try:
        url = f"https://metals-api.com/api/latest?access_key={api_key}&base=EUR&symbols=XAU,XAG"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success"):
                rates = data.get("rates", {})
                # Metals-API geeft 1/prijs terug (hoeveel XAU per 1 EUR)
                xau_rate = rates.get("XAU", 0)
                xag_rate = rates.get("XAG", 0)
                if xau_rate > 0 and xag_rate > 0:
                    gold_eur = 1.0 / xau_rate
                    silver_eur = 1.0 / xag_rate
                    print(f"✅ [Fallback] Metals-API: Goud €{gold_eur:.2f} | Zilver €{silver_eur:.2f}")
                    return gold_eur, silver_eur
    except Exception as e:
        print(f"⚠️ [Fallback] Metals-API fout: {e}")
    return None, None

def _fetch_goldapi():
    """
    Fallback 2: GoldAPI.io
    Gratis: 100 calls/maand. Retourneert goud/zilver in EUR.
    """
    api_key = os.environ.get("GOLDAPI_KEY", "")
    if not api_key:
        return None, None
    
    gold_eur = None
    silver_eur = None
    
    try:
        headers = {"x-access-token": api_key, "Content-Type": "application/json"}
        
        # Goud ophalen
        resp_gold = requests.get("https://www.goldapi.io/api/XAU/EUR", headers=headers, timeout=10)
        if resp_gold.status_code == 200:
            data = resp_gold.json()
            gold_eur = data.get("price", 0)
        
        # Zilver ophalen
        resp_silver = requests.get("https://www.goldapi.io/api/XAG/EUR", headers=headers, timeout=10)
        if resp_silver.status_code == 200:
            data = resp_silver.json()
            silver_eur = data.get("price", 0)
        
        if gold_eur and silver_eur:
            print(f"✅ [Fallback] GoldAPI: Goud €{gold_eur:.2f} | Zilver €{silver_eur:.2f}")
            return gold_eur, silver_eur
    except Exception as e:
        print(f"⚠️ [Fallback] GoldAPI fout: {e}")
    return None, None

def _get_fallback_prices():
    """
    Probeert alternatieve bronnen voor spotprijzen.
    Cached resultaat voor 1 uur om API calls te sparen.
    Volgorde: Metals-API → GoldAPI.io → cache
    """
    now = time.time()
    
    # Gebruik cache als deze minder dan 1 uur oud is
    if _price_cache["timestamp"] > 0 and (now - _price_cache["timestamp"]) < 3600:
        if _price_cache["gold_eur"] > 0:
            print(f"📦 [Fallback] Gebruik gecachte prijs ({_price_cache['source']}, {int((now - _price_cache['timestamp'])/60)} min oud)")
            return _price_cache["gold_eur"], _price_cache["silver_eur"]
    
    # Fallback 1: Metals-API
    gold, silver = _fetch_metals_api()
    if gold and silver:
        _price_cache.update({"gold_eur": gold, "silver_eur": silver, "timestamp": now, "source": "Metals-API"})
        return gold, silver
    
    # Fallback 2: GoldAPI.io
    gold, silver = _fetch_goldapi()
    if gold and silver:
        _price_cache.update({"gold_eur": gold, "silver_eur": silver, "timestamp": now, "source": "GoldAPI"})
        return gold, silver
    
    # Geen fallback beschikbaar — gebruik oude cache als die er is
    if _price_cache["gold_eur"] > 0:
        print(f"⚠️ [Fallback] Alle bronnen failen. Gebruik oude cache ({_price_cache['source']})")
        return _price_cache["gold_eur"], _price_cache["silver_eur"]
    
    print("❌ [Fallback] Geen enkele prijsbron beschikbaar.")
    return 0.0, 0.0

def get_live_spot_prices():
    """
    Haalt actuele goud- en zilverprijzen op.
    Primair: Yahoo Finance (onbeperkt, doordeweeks)
    Fallback: Metals-API → GoldAPI.io (weekenden/nachts)
    """
    gold_price_eur = 0.0
    silver_price_eur = 0.0
    
    # --- Primaire bron: Yahoo Finance ---
    try:
        # Gebruik een custom session met User-Agent om 'Expecting value' errors (bot-checks) te omzeilen
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
        })
        
        gold_usd = yf.Ticker("GC=F", session=session)
        silver_usd = yf.Ticker("SI=F", session=session)
        eur_usd = yf.Ticker("EURUSD=X", session=session)
        
        g_usd_price = float(gold_usd.history(period="1d")['Close'].iloc[-1])
        s_usd_price = float(silver_usd.history(period="1d")['Close'].iloc[-1])
        fx_rate = float(eur_usd.history(period="1d")['Close'].iloc[-1])
        
        gold_price_eur = g_usd_price / fx_rate
        silver_price_eur = s_usd_price / fx_rate
        
        # Cache bijwerken met Yahoo data (voor als fallback later nodig is)
        if gold_price_eur > 0:
            _price_cache.update({
                "gold_eur": gold_price_eur, 
                "silver_eur": silver_price_eur, 
                "timestamp": time.time(), 
                "source": "Yahoo Finance"
            })
    except Exception as e:
        print(f"⚠️ Yahoo Finance faalt ({e}). Probeer fallback...")
    
    # --- Fallback als Yahoo faalt ---
    if gold_price_eur <= 0 or silver_price_eur <= 0:
        gold_price_eur, silver_price_eur = _get_fallback_prices()
    
    physical_premium_percentage = 0.00 
    
    return {
        "gold_eur_oz_paper": float(gold_price_eur),
        "silver_eur_oz_paper": float(silver_price_eur),
        "gold_eur_oz_physical": float(gold_price_eur * (1 + physical_premium_percentage)),
        "silver_eur_oz_physical": float(silver_price_eur * (1 + physical_premium_percentage))
    }

def get_gold_volatility():
    """
    Haalt de goudprijs-daling op van de afgelopen 24 uur.
    Retourneert een negatief percentage (bijv. -2.5) als het is gedaald.
    Is het gestegen of gelijk gebleven? Dan 0.0
    """
    try:
        gold_ticker = yf.Ticker("GC=F")
        hist = gold_ticker.history(period="5d")
        if len(hist) >= 2:
            close_yesterday = float(hist['Close'].iloc[-2])
            close_today = float(hist['Close'].iloc[-1])
            
            percent_change = ((close_today - close_yesterday) / close_yesterday) * 100
            
            # We zijn alleen geïnteresseerd in een daling (panic selling op MP)
            if percent_change < 0:
                return round(percent_change, 2)
        return 0.0
    except Exception as e:
        print(f"⚠️ Kon goud volatiliteit niet ophalen ({e}).")
        return 0.0

def calculate_intrinsic_value(weight_oz, current_spot_price):
    """
    Berekent de pure materiaalwaarde op basis van gewicht (in Oz) en de spotprijs.
    """
    if weight_oz is None:
        return 0.0
    return weight_oz * current_spot_price


def check_flash_dip(metal="silver", drop_threshold=2.5, rsi_threshold=35):
    """
    Controleert of een metaal ("gold" of "silver") plotseling meer dan `drop_threshold` % 
    is gedaald ten opzichte van de 24-uurs piek én of de 14-period uurs-RSI onder `rsi_threshold` ligt.
    
    Retourneert een dict dict met:
    {"is_dip": bool, "drop_pct": float, "rsi": float, "current_price": float, "peak_price": float}
    of None als de api faalt.
    """
    try:
        ticker = "SI=F" if metal.lower() == "silver" else "GC=F"
        data = yf.Ticker(ticker)
        
        # Haal 3 dagen 1-uur data op (voor 14-period RSI en ~24u history)
        hist = data.history(period="3d", interval="1h")
        
        if len(hist) < 15:
            return None
        
        # 1. Bereken RSI (14 periodes)
        delta = hist['Close'].diff()
        gain = delta.where(delta > 0, 0.0).rolling(window=14).mean()
        loss = -delta.where(delta < 0, 0.0).rolling(window=14).mean()
        
        # Voorkom deling door 0
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        current_rsi = rsi.iloc[-1]
        if pd.isna(current_rsi) or pd.isna(loss.iloc[-1]) or loss.iloc[-1] == 0:
            current_rsi = 50.0 # Neutraal als hij plat is
            
        # 2. Bereken Piek-naar-Dal in de afgelopen 24-uur 
        # (laatste 24 rijen in een 1-uur interval dataset)
        last_24h = hist.tail(24)
        peak_price = last_24h['High'].max()
        current_price = last_24h['Close'].iloc[-1]
        
        drop_pct = ((current_price - peak_price) / peak_price) * 100
        
        # Is the drop deep enough AND is the market panicking (RSI low)?
        is_dip = (drop_pct <= -drop_threshold) and (current_rsi <= rsi_threshold)
        
        return {
            "is_dip": bool(is_dip),
            "drop_pct": round(float(drop_pct), 2),
            "rsi": round(float(current_rsi), 2),
            "current_price": round(float(current_price), 2),
            "peak_price": round(float(peak_price), 2)
        }
    except Exception as e:
        print(f"⚠️ [Flash Dip] Fout bij ophalen spot analyse voor {metal}: {e}")
        return None

def validate_price_sanity(metal: str, price_entered: float, weight_oz: float) -> tuple[bool, str]:
    """
    AI Poortwachter: Controleert of de verhouding tussen prijs en gewicht realistisch is.
    Voorkomt typo's of scraping fouten voordat ze het platform of Telegram in gaan.
    Returns: (is_valid, error_message)
    """
    if price_entered <= 0 or weight_oz <= 0:
        return False, "Prijs of gewicht kan niet 0 of negatief zijn."
        
    spot_prices = get_live_spot_prices()
    spot_val = spot_prices.get("gold_eur_oz_physical", 0) if "goud" in metal.lower() else spot_prices.get("silver_eur_oz_physical", 0)
    
    if spot_val <= 0:
        return True, "" # Geen spot referentie beschikbaar, blokkeer de actie niet.
        
    intrinsic_value = spot_val * weight_oz
    
    # Tolerantie Bandbreedte  
    max_discount = 0.5  # Max -50% onder spot
    max_premium = 2.5   # Max +150% boven spot
    
    if price_entered < (intrinsic_value * max_discount):
        return False, f"De prijs is méér dan 50% lager dan de spotwaarde (€{intrinsic_value:.0f} voor {weight_oz} Oz). Controleer op een typfout in gewicht of prijs."
        
    if price_entered > (intrinsic_value * max_premium):
        return False, f"De prijs is extreem (>150%) hoger dan de spotwaarde (€{intrinsic_value:.0f} voor {weight_oz} Oz). Klopt dit gewicht wel?"
        
    return True, ""
