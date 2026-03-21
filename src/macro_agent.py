import yfinance as yf
import json
import os
import sys
import datetime
import requests
from dotenv import load_dotenv
from ai_router import router_generate_content
from bs4 import BeautifulSoup

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

_macro_cache = {"data": None, "last_fetch": None}

def fetch_macro_data():
    """
    Haalt de belangrijkste macro-economische indicatoren op via Yahoo Finance.
    - DX-Y.NYB : US Dollar Index (DXY)
    - ^TNX : US 10-Year Treasury Yield
    - GC=F : Gold Futures
    - SI=F : Silver Futures
    """
    now = datetime.datetime.now()
    if _macro_cache["last_fetch"] and (now - _macro_cache["last_fetch"]).total_seconds() < 3600:
        print("[Macro Agent] Ophalen actuele macro-economische data... (CACHED)")
        return _macro_cache["data"]
        
    print("[Macro Agent] Ophalen actuele macro-economische data... (LIVE)")
    
    tickers = {
        "dxy": "DX-Y.NYB",
        "us10y": "^TNX",
        "gold_futures": "GC=F",
        "silver_futures": "SI=F"
    }
    
    data = {}
    
    try:
        for name, symbol in tickers.items():
            ticker_obj = yf.Ticker(symbol)
            hist = ticker_obj.history(period="5d")
            
            if not hist.empty:
                current_price = hist['Close'].iloc[-1]
                prev_price = hist['Close'].iloc[-2] if len(hist) > 1 else current_price
                change_pct = ((current_price - prev_price) / prev_price) * 100
                
                data[name] = {
                    "huidige_waarde": round(current_price, 2),
                    "dag_verandering_pct": round(change_pct, 2)
                }
            else:
                data[name] = {"huidige_waarde": None, "dag_verandering_pct": None}
                
        # Bereken de Gold/Silver ratio
        try:
            gs_ratio = data["gold_futures"]["huidige_waarde"] / data["silver_futures"]["huidige_waarde"]
            data["gold_silver_ratio"] = round(gs_ratio, 2)
        except Exception:
            data["gold_silver_ratio"] = None
            
        _macro_cache["data"] = data
        _macro_cache["last_fetch"] = now
        return data

    except Exception as e:
        print(f"❌ [Macro Agent] Fout tijdens ophalen macro data: {e}")
        return None

_reddit_cache = {"data": None, "last_fetch": None}

def fetch_reddit_sentiment():
    """
    Haalt sentiment op van meerdere Reddit-subreddits voor goud EN zilver.
    Bronnen: r/Gold, r/Silverbugs, r/Wallstreetsilver, r/Bullion, r/investing
    """
    subreddits = [
        ("Gold", "r/Gold (Goud)"),
        ("Silverbugs", "r/Silverbugs (Zilver)"),
        ("Wallstreetsilver", "r/Wallstreetsilver (Zilver Hype)"),
        ("Bullion", "r/Bullion (Breed)"),
    ]
    
    headers = {"User-agent": "AurumBot 1.0 (by /u/Antigravity)"}
    all_titles = []
    sources_ok = 0
    
    now = datetime.datetime.now()
    if _reddit_cache["last_fetch"] and (now - _reddit_cache["last_fetch"]).total_seconds() < 3600:
        print("[Macro Agent] Ophalen Reddit sentiment (multi-subreddit)... (CACHED)")
        return _reddit_cache["data"]
        
    print("[Macro Agent] Ophalen Reddit sentiment (multi-subreddit)... (LIVE)")
    
    for sub, label in subreddits:
        try:
            url = f"https://www.reddit.com/r/{sub}/hot.json?limit=5"
            response = requests.get(url, headers=headers, timeout=5)
            if response.status_code == 200:
                data = response.json()
                titles = [
                    post['data']['title'] 
                    for post in data['data']['children'] 
                    if not post['data']['stickied']
                ][:3]  # Max 3 per subreddit
                for t in titles:
                    all_titles.append(f"[{label}] {t}")
                sources_ok += 1
        except Exception:
            continue
    
    # Extra bron: Kitco News RSS (professioneel sentiment)
    try:
        kitco_url = "https://www.kitco.com/feed/rss/news/gold"
        resp = requests.get(kitco_url, headers={"User-agent": "AurumBot 1.0"}, timeout=5)
        if resp.status_code == 200:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "xml")
            items = soup.find_all("item", limit=3)
            for item in items:
                title = item.find("title")
                if title:
                    all_titles.append(f"[Kitco News] {title.get_text(strip=True)}")
            sources_ok += 1
    except Exception:
        pass
    
    print(f"✅ [Macro Agent] Sentiment: {len(all_titles)} posts van {sources_ok} bronnen")
    
    if all_titles:
        result = "\n".join([f"- {t}" for t in all_titles])
        _reddit_cache["data"] = result
        _reddit_cache["last_fetch"] = now
        return result
        
    _reddit_cache["data"] = "Kon geen Reddit/Kitco data ophalen."
    _reddit_cache["last_fetch"] = now
    return _reddit_cache["data"]

# ============================================================
# AUTOMATISCHE ECONOMISCHE KALENDER
# Bron 1: Financial Modeling Prep API (gratis, 250 calls/dag)
# Bron 2: Investing.com scrape (fallback)
# Cache: 1x per dag ophalen, daarna uit geheugen
# ============================================================
_calendar_cache = {"events": [], "last_fetch": None, "source": None, "health": {}}

# Events die relevant zijn voor goud/zilver
GOLD_RELEVANT_KEYWORDS = [
    "fomc", "fed", "interest rate", "rente", "ecb", "boe",
    "non-farm", "nonfarm", "nfp", "payroll",
    "cpi", "inflation", "inflatie",
    "ppi", "producer price",
    "gdp", "bbp", "pmi", "manufacturing",
    "gold", "silver", "goud", "zilver",
    "treasury", "yield", "dollar", "dxy",
    "unemployment", "werkloosheid", "jobless",
    "comex", "opec", "crude", "oil"
]

def _is_gold_relevant(event_name):
    """Checkt of een event relevant is voor de edelmetaalmarkt."""
    name_lower = event_name.lower()
    return any(kw in name_lower for kw in GOLD_RELEVANT_KEYWORDS)

def _fetch_fmp_calendar():
    """
    Bron 3 (GEPARKEERD): Financial Modeling Prep API
    Gratis tier: 250 calls/dag. Retourneert JSON met economische events.
    Activeer door FMP_API_KEY in .env te zetten.
    """
    api_key = os.environ.get("FMP_API_KEY", "")
    if not api_key:
        # Geparkeerd: geen key = overslaan zonder waarschuwing
        return None
    
    try:
        vandaag = datetime.date.today()
        tot = vandaag + datetime.timedelta(days=30)  # 30 dagen vooruit
        url = (
            f"https://financialmodelingprep.com/api/v3/economic_calendar"
            f"?from={vandaag.isoformat()}&to={tot.isoformat()}&apikey={api_key}"
        )
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            print(f"⚠️ [Kalender] FMP API fout: HTTP {resp.status_code}")
            _calendar_cache["health"]["fmp"] = f"FOUT (HTTP {resp.status_code})"
            return None
        
        data = resp.json()
        events = []
        for item in data:
            event_name = item.get("event", "")
            if not _is_gold_relevant(event_name):
                continue
            
            # Parse datum
            date_str = item.get("date", "")[:10]  # "2026-03-18T00:00:00.000+0000"
            try:
                event_date = datetime.date.fromisoformat(date_str)
            except ValueError:
                continue
            
            delta = (event_date - vandaag).days
            country = item.get("country", "")
            impact = "🔴" if item.get("impact", "").lower() == "high" else "🟡"
            
            events.append({
                "datum": event_date,
                "delta_days": delta,
                "event": f"{impact} {event_name} ({country})",
                "impact": item.get("impact", "Medium"),
            })
        
        _calendar_cache["health"]["fmp"] = f"OK ({len(events)} events)"
        print(f"✅ [Kalender] FMP: {len(events)} relevante events gevonden")
        return events
        
    except Exception as e:
        print(f"❌ [Kalender] FMP fout: {e}")
        _calendar_cache["health"]["fmp"] = f"FOUT ({e})"
        return None

def _fetch_forexfactory_calendar():
    """
    Bron 1 (PRIMAIR): ForexFactory economic calendar scrape.
    Gebruikt cloudscraper om Cloudflare te bypassen.
    """
    try:
        import cloudscraper
        from bs4 import BeautifulSoup
        
        scraper = cloudscraper.create_scraper()
        
        # ForexFactory week URL — pakt de huidige week + volgende week
        vandaag = datetime.date.today()
        url = "https://www.forexfactory.com/calendar?week=this"
        resp = scraper.get(url, timeout=15)
        
        if resp.status_code != 200:
            print(f"⚠️ [Kalender] ForexFactory fout: HTTP {resp.status_code}")
            _calendar_cache["health"]["forexfactory"] = f"FOUT (HTTP {resp.status_code})"
            return None
        
        soup = BeautifulSoup(resp.text, "html.parser")
        events = []
        current_date = None
        
        # ForexFactory structuur: <tr class="calendar__row calendar_row">
        rows = soup.select("tr.calendar__row")
        for row in rows:
            try:
                # Datum cell — wordt alleen getoond bij eerste event van die dag
                date_cell = row.select_one("td.calendar__date span")
                if date_cell:
                    date_text = date_cell.get_text(strip=True)
                    if date_text:
                        # Parse "Mon Mar 18" formaat
                        try:
                            parsed = datetime.datetime.strptime(f"{date_text} {vandaag.year}", "%a%b %d %Y")
                            current_date = parsed.date()
                            # Als datum in het verleden ligt en > 300 dagen, is het volgend jaar
                            if (current_date - vandaag).days < -300:
                                current_date = current_date.replace(year=vandaag.year + 1)
                        except ValueError:
                            pass
                
                if not current_date:
                    continue
                
                # Event naam
                event_cell = row.select_one("td.calendar__event span")
                if not event_cell:
                    continue
                event_name = event_cell.get_text(strip=True)
                
                if not event_name or not _is_gold_relevant(event_name):
                    continue
                
                # Impact level
                impact_cell = row.select_one("td.calendar__impact span")
                impact_level = "Medium"
                if impact_cell:
                    impact_class = " ".join(impact_cell.get("class", []))
                    if "high" in impact_class or "red" in impact_class:
                        impact_level = "High"
                    elif "medium" in impact_class or "ora" in impact_class:
                        impact_level = "Medium"
                    # Alleen titel als fallback
                    title = impact_cell.get("title", "").lower()
                    if "high" in title:
                        impact_level = "High"
                
                impact_icon = "🔴" if impact_level == "High" else "🟡"
                
                # Valuta/Land
                currency_cell = row.select_one("td.calendar__currency")
                currency = currency_cell.get_text(strip=True) if currency_cell else ""
                
                delta = (current_date - vandaag).days
                if 0 <= delta <= 30:  # Scannen tot 30 dagen vooruit
                    events.append({
                        "datum": current_date,
                        "delta_days": delta,
                        "event": f"{impact_icon} {event_name} ({currency})",
                        "impact": impact_level,
                    })
            except Exception:
                continue
        
        # Haal volgende week op als we minder dan 7 dagen hebben
        if all(e["delta_days"] < 7 for e in events) if events else True:
            try:
                url_next = "https://www.forexfactory.com/calendar?week=next"
                resp_next = scraper.get(url_next, timeout=15)
                if resp_next.status_code == 200:
                    soup_next = BeautifulSoup(resp_next.text, "html.parser")
                    current_date_next = None
                    rows_next = soup_next.select("tr.calendar__row")
                    for row in rows_next:
                        try:
                            date_cell = row.select_one("td.calendar__date span")
                            if date_cell:
                                date_text = date_cell.get_text(strip=True)
                                if date_text:
                                    try:
                                        parsed = datetime.datetime.strptime(f"{date_text} {vandaag.year}", "%a%b %d %Y")
                                        current_date_next = parsed.date()
                                        if (current_date_next - vandaag).days < -300:
                                            current_date_next = current_date_next.replace(year=vandaag.year + 1)
                                    except ValueError:
                                        pass
                            
                            if not current_date_next:
                                continue
                            
                            event_cell = row.select_one("td.calendar__event span")
                            if not event_cell:
                                continue
                            event_name = event_cell.get_text(strip=True)
                            if not event_name or not _is_gold_relevant(event_name):
                                continue
                            
                            impact_cell = row.select_one("td.calendar__impact span")
                            impact_level = "Medium"
                            if impact_cell:
                                impact_class = " ".join(impact_cell.get("class", []))
                                if "high" in impact_class or "red" in impact_class:
                                    impact_level = "High"
                                title = impact_cell.get("title", "").lower()
                                if "high" in title:
                                    impact_level = "High"
                            
                            impact_icon = "🔴" if impact_level == "High" else "🟡"
                            currency_cell = row.select_one("td.calendar__currency")
                            currency = currency_cell.get_text(strip=True) if currency_cell else ""
                            
                            delta = (current_date_next - vandaag).days
                            if 0 <= delta <= 30:  # 30 dagen vooruit
                                events.append({
                                    "datum": current_date_next,
                                    "delta_days": delta,
                                    "event": f"{impact_icon} {event_name} ({currency})",
                                    "impact": impact_level,
                                })
                        except Exception:
                            continue
            except Exception:
                pass
        
        # Haal ook 2 weken vooruit op voor vroege anticipatie
        try:
            url_2weeks = "https://www.forexfactory.com/calendar?week=2"
            resp_2w = scraper.get(url_2weeks, timeout=15)
            if resp_2w.status_code == 200:
                soup_2w = BeautifulSoup(resp_2w.text, "html.parser")
                current_date_2w = None
                rows_2w = soup_2w.select("tr.calendar__row")
                for row in rows_2w:
                    try:
                        date_cell = row.select_one("td.calendar__date span")
                        if date_cell:
                            date_text = date_cell.get_text(strip=True)
                            if date_text:
                                try:
                                    parsed = datetime.datetime.strptime(f"{date_text} {vandaag.year}", "%a%b %d %Y")
                                    current_date_2w = parsed.date()
                                    if (current_date_2w - vandaag).days < -300:
                                        current_date_2w = current_date_2w.replace(year=vandaag.year + 1)
                                except ValueError:
                                    pass
                        if not current_date_2w:
                            continue
                        event_cell = row.select_one("td.calendar__event span")
                        if not event_cell:
                            continue
                        event_name = event_cell.get_text(strip=True)
                        if not event_name or not _is_gold_relevant(event_name):
                            continue
                        impact_cell = row.select_one("td.calendar__impact span")
                        impact_level = "High" if impact_cell and ("high" in " ".join(impact_cell.get("class", [])) or "high" in impact_cell.get("title", "").lower()) else "Medium"
                        impact_icon = "🔴" if impact_level == "High" else "🟡"
                        currency_cell = row.select_one("td.calendar__currency")
                        currency = currency_cell.get_text(strip=True) if currency_cell else ""
                        delta = (current_date_2w - vandaag).days
                        if 14 < delta <= 30:  # Alleen events die buiten de eerste 2 weken vallen
                            events.append({
                                "datum": current_date_2w,
                                "delta_days": delta,
                                "event": f"{impact_icon} {event_name} ({currency})",
                                "impact": impact_level,
                            })
                    except Exception:
                        continue
        except Exception:
            pass
        
        _calendar_cache["health"]["forexfactory"] = f"OK ({len(events)} events)"
        print(f"✅ [Kalender] ForexFactory: {len(events)} relevante events gevonden")
        return events if events else None
        
    except Exception as e:
        print(f"❌ [Kalender] ForexFactory fout: {e}")
        _calendar_cache["health"]["forexfactory"] = f"FOUT ({e})"
        return None

def _fetch_investing_calendar():
    """
    Bron 2 (FALLBACK): Investing.com economic calendar scrape.
    Scrapt de HTML kalender pagina voor high-impact events.
    """
    try:
        from bs4 import BeautifulSoup
        
        url = "https://www.investing.com/economic-calendar/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            print(f"⚠️ [Kalender] Investing.com fout: HTTP {resp.status_code}")
            _calendar_cache["health"]["investing"] = f"FOUT (HTTP {resp.status_code})"
            return None
        
        soup = BeautifulSoup(resp.text, "html.parser")
        vandaag = datetime.date.today()
        events = []
        
        # Investing.com gebruikt <tr> rows met event data
        rows = soup.select("tr.js-event-item")
        for row in rows[:50]:  # Max 50 rijen checken
            try:
                # Event naam
                event_cell = row.select_one("td.event a")
                if not event_cell:
                    continue
                event_name = event_cell.get_text(strip=True)
                
                if not _is_gold_relevant(event_name):
                    continue
                
                # Impact (aantal bulls/stieren iconen)
                impact_cell = row.select_one("td.sentiment")
                impact_level = "Medium"
                if impact_cell:
                    bulls = impact_cell.select("i.grayFullBullishIcon")
                    if len(bulls) >= 3:
                        impact_level = "High"
                
                impact_icon = "🔴" if impact_level == "High" else "🟡"
                
                # Land
                flag = row.select_one("td.flagCur span")
                country = flag.get("title", "") if flag else ""
                
                # Datum
                date_attr = row.get("data-event-datetime", "")
                if date_attr:
                    try:
                        event_date = datetime.date.fromisoformat(date_attr[:10])
                        delta = (event_date - vandaag).days
                    except ValueError:
                        delta = 0
                        event_date = vandaag
                else:
                    delta = 0
                    event_date = vandaag
                
                if 0 <= delta <= 30:  # 30 dagen vooruit
                    events.append({
                        "datum": event_date,
                        "delta_days": delta,
                        "event": f"{impact_icon} {event_name} ({country})",
                        "impact": impact_level,
                    })
            except Exception:
                continue
        
        _calendar_cache["health"]["investing"] = f"OK ({len(events)} events)"
        print(f"✅ [Kalender] Investing.com: {len(events)} relevante events gevonden")
        return events if events else None
        
    except Exception as e:
        print(f"❌ [Kalender] Investing.com fout: {e}")
        _calendar_cache["health"]["investing"] = f"FOUT ({e})"
        return None

def get_upcoming_events():
    """
    Haalt economische events op uit automatische bronnen.
    Cached resultaat 1x per dag. Fallback: ForexFactory → Investing.com → (FMP geparkeerd).
    """
    vandaag = datetime.date.today()
    
    # Check cache: als we vandaag al hebben opgehaald, gebruik cache
    if _calendar_cache["last_fetch"] == vandaag and _calendar_cache["events"]:
        events = _calendar_cache["events"]
    else:
        # Bron 1: ForexFactory (primair)
        events = _fetch_forexfactory_calendar()
        
        # Bron 2: Investing.com (fallback)
        if not events:
            events = _fetch_investing_calendar()
        
        # Bron 3: FMP API (geparkeerd — activeer door FMP_API_KEY in .env te zetten)
        if not events:
            events = _fetch_fmp_calendar()
        
        # Ultieme fallback
        if not events:
            print("⚠️ [Kalender] Alle bronnen gefaald.")
            _calendar_cache["health"]["status"] = "ALLE BRONNEN GEFAALD"
            events = []
        
        # Cache opslaan
        _calendar_cache["events"] = events or []
        _calendar_cache["last_fetch"] = vandaag
        _calendar_cache["source"] = (
            "ForexFactory" if _calendar_cache["health"].get("forexfactory", "").startswith("OK")
            else "Investing.com" if _calendar_cache["health"].get("investing", "").startswith("OK")
            else "FMP" if _calendar_cache["health"].get("fmp", "").startswith("OK")
            else "Geen"
        )
    
    # Formatteer output
    if not events:
        return "Geen relevante events gevonden in de komende 30 dagen."
    
    # Sorteer op datum, high-impact eerst
    events.sort(key=lambda e: (e["datum"], e["impact"] != "High"))
    
    lines = []
    for e in events[:12]:  # Max 12 events tonen (was: 8)
        # Geef een duidelijke tijdsaanduiding voor vroege events
        if e['delta_days'] == 0:
            timing = "VANDAAG"
        elif e['delta_days'] == 1:
            timing = "MORGEN"
        elif e['delta_days'] <= 7:
            timing = f"OVER {e['delta_days']} DAGEN"
        else:
            timing = f"OVER {e['delta_days']} DAGEN ({e['datum'].strftime('%d %b')})"
        lines.append(f"{timing}: {e['event']}")
    
    return "\n".join(lines)

def get_calendar_health():
    """Retourneert de status van de kalender bronnen voor monitoring."""
    return {
        "bron_actief": _calendar_cache.get("source", "Nog niet opgehaald"),
        "laatste_fetch": str(_calendar_cache.get("last_fetch", "Nooit")),
        "events_cached": len(_calendar_cache.get("events", [])),
        "fmp_status": _calendar_cache.get("health", {}).get("fmp", "Niet geprobeerd"),
        "investing_status": _calendar_cache.get("health", {}).get("investing", "Niet geprobeerd"),
    }

def analyze_macro_sentiment(macro_data, reddit_texts, events_text):
    """
    Geeft de ruwe economische data aan de AI Router om een score en een beleggingsadvies te genereren.
    """
    if not macro_data:
        return {"macro_score": 0, "advies_samenvatting": "Geen macro data beschikbaar."}
        
    try:
        macro_summary = "\n".join([f"{k}: {v}" for k, v in macro_data.items()])
        
        system_instruction = """
        Jij bent een Financial Macro Analyst. Analyseer de volgende data en geef een sentiment-score voor Goud/Zilver.
        REGELS:
        - Score: -100 (Extreem Bearish) tot +100 (Extreem Bullish).
        - Samenvatting: MAX 3 korte zinnen.
        - Geef EXACT dit JSON formaat: 
        {
            "macro_score": 85, 
            "advies_samenvatting": "...",
            "sentiment_alert": "...",
            "kalender_alert": "..."
        }
        """
        
        prompt = f"""
        DATA:
        {macro_summary}
        
        REDDIT SENTIMENT:
        {reddit_texts}
        
        UPCOMING EVENTS:
        {events_text}
        
        INSTRUCTIES:
        1. Wat is de impact van DXY en Yield op goud/zilver?
        2. Is de Gold/Silver ratio gunstig?
        3. Filter social media sentiment op hype/paniek.
        4. Bekijk de kalender voor volatiliteit.
        """
        
        # Router aanroepen
        return router_generate_content(
            prompt=prompt,
            system_instruction=system_instruction,
            model_override="gemma2:2b" # Sneller tekstmodel voor macro analyse op Pi
        )

    except Exception as e:
        print(f"❌ [Macro Agent] Fout tijdens analyse via Router: {e}")
        return {
            "macro_score": 0, 
            "advies_samenvatting": f"Macro analyse gefaald: {e}",
            "sentiment_alert": "Fout",
            "kalender_alert": "Fout"
        }

if __name__ == "__main__":
    current_data = fetch_macro_data()
    reddit_data = fetch_reddit_sentiment()
    event_data = get_upcoming_events()
    
    print("\nGenereren van AI Sentiment Score...")
    sentiment = analyze_macro_sentiment(current_data, reddit_data, event_data)
    print("AI Oordeel:")
    print(json.dumps(sentiment, indent=4))
