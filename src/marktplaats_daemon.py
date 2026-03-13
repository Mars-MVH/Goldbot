import os
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from marktplaats_scraper import scrape_marktplaats_search
from expert_agent import pre_scan_image
from pricing import get_live_spot_prices, validate_price_sanity
from dealer_scraper import fetch_dealer_premiums, get_lowest_ask_price, get_highest_bid_price
from database import ad_exists, save_ad, log_radar_stats

logger = logging.getLogger(__name__)

# SQLite Database handles seen URLs now

# Keywords om op te zoeken.
TARGET_KEYWORDS = [
    "Krugerrand",
    "Maple Leaf Goud",
    "Goudbaar 10 gram",
    "Goudbaar 1 Oz",
    "Gouden tientje",
    # Prio 3: Foutieve categorie snipe
    "gouden munt penning",
    "goud antiek munten",
    "zilveren munt beleggen",
]

# ============================================================
# BLACKLIST: Woorden die aangeven dat een advertentie GEEN
# echt edelmetaal is. Checkt titel + beschrijving VOORDAT
# we de dure Gemini AI inschakelen. Bespaart API credits.
# ============================================================
BLACKLIST_KEYWORDS = [
    # --- Nederlands (Nep / Replica) ---
    "replica", "verguld", "vergulde", "gold plated", "silver plated",
    "nep", "namaak", "kopie", "imitatie", "fantasie", "fantasy",
    "doublé", "double", "goudkleurig", "zilverkleurig",
    "kleurig", "goudlaagje", "opleg", "vermeil",
    # --- Engels (Fake / Plated) ---
    "plated", "clad", "copy", "tribute", "novelty", "souvenir",
    "faux", "fake", "counterfeit", "electroplated",
    "gold filled", "gold-filled", "gf ", " rgp",
    # --- Restrike / Herdenkings ---
    "restrike", "herslag",
    # --- Sieraden (Geen Bullion) ---
    "ketting", "armband", "ring ", "oorbel", "hanger", "broche",
    "sieraad", "sieraden", "juweel", "necklace", "bracelet",
    # --- Veilinghuizen / Externe platformen ---
    "catawiki", "veiling", "auction", "troostwijk", "bva", 
    "heritage", "kiav",
    # --- Overig Irrelevant ---
    "magneet", "magnet", "lot munten", "partij munten",
    "euromunten", "euro munt", "verzamelmap", "album",
    "chocolade", "chocolate", "speelgoed", "toy",
]

def is_blacklisted(title, description=""):
    """
    Controleert of een advertentie een of meer blacklist-woorden bevat
    in de titel of beschrijving. Case-insensitive.
    Retourneert het gevonden verboden woord, of None als het schoon is.
    """
    combined = f"{title} {description}".lower()
    for keyword in BLACKLIST_KEYWORDS:
        if keyword in combined:
            return keyword
    return None

# ============================================================
# DYNAMISCHE MARGE: Minimale winstdrempel verschilt per type.
# Standaard bullion (Krugerrand) = lage spread, dus 3% is genoeg.
# Historische munten (Tientjes) = hoge spread, dus 8% nodig.
# ============================================================
MARGIN_MAP = {
    "krugerrand":     3.0,
    "maple leaf":     3.0,
    "philharmoniker": 3.0,
    "eagle":          3.0,
    "kangaroo":       3.0,
    "panda":          5.0,
    "baar":           4.0,
    "bar":            4.0,
    "tientje":        8.0,
    "gulden":         8.0,
    "dukaat":         8.0,
    "ducat":          8.0,
    "willem":         8.0,
    "wilhelmina":     8.0,
    "sovereign":      6.0,
}
DEFAULT_MARGIN = 3.0

def get_dynamic_margin(pre_scan, title=""):
    """
    Bepaalt de minimale arbitrage-marge die nodig is
    op basis van het producttype uit de AI pre-scan of de titel.
    """
    # Combineer alle beschikbare tekst
    search_text = f"{pre_scan.get('merk_of_muntnaam', '')} {pre_scan.get('type', '')} {title}".lower()
    
    for key, margin in MARGIN_MAP.items():
        if key in search_text:
            return margin
    
    # Zilver heeft sowieso een hogere drempel (lagere absolute waarde)
    if pre_scan.get("metaal", "").lower() == "zilver":
        return 5.0
    
    return DEFAULT_MARGIN

async def run_marktplaats_radar(context):
    """
    De achtergrond 'Radar' die periodiek over Marktplaats zoekt.
    - Haalt N advertenties per keyword op.
    - Checkt via AI Pass 1 of het echt goud is.
    - Berekent de dealers-prijs en kijkt of er > 2% Arbitrage Marge is.
    - Zo ja: Push Notification naar Telegram met [Start Onderhandeling] knop.
    """
    chat_id = context.job.data.get('chat_id')
    logger.info("📡 [Radar] Start periodieke Marktplaats scan...")
    
    # Tijdelijke file opslaan (omdat pre_scan_image file_paths verwacht, geen URLs lokaal).
    # Omdat we headless scrapen en initieel puur op tekst/prijs filteren, downloaden we pas fotos
    # als we pre-scannen.
    
    import requests
    from PIL import Image
    from io import BytesIO
    
    spot_prices: dict = get_live_spot_prices()
    
    # Radar stats counters
    stat_scanned = 0
    stat_filtered = 0
    stat_ai = 0
    stat_deals = 0

    import asyncio
    import functools
    
    for keyword in TARGET_KEYWORDS:
        try:
            results = await asyncio.to_thread(scrape_marktplaats_search, keyword, max_results=3)
            
            for ad in results:
                url = ad.get("url")
                
                price_float = ad.get("price_float")
                is_bieden = False
                
                # ========== BIEDEN-ADVERTENTIES (Sprint 2) ==========
                # Ads zonder vaste prijs ('Bieden') zijn potentiële jackpots.
                # We scannen ze wél via AI, maar markeren ze duidelijk.
                if not price_float or price_float < 10:
                    price_raw = ad.get("price_raw", "").lower()
                    if "bied" in price_raw or price_raw == "" or "nader" in price_raw:
                        is_bieden = True
                        price_float = 0.0  # Zet op 0 zodat de rest van de pipeline werkt
                    else:
                        continue  # Echt onbruikbaar (geen prijs, geen bieden)

                # Controleer de SQLite database om onnodige AI Quota burn te voorkomen
                if ad_exists(url, price_float if price_float > 0 else -1):
                    logger.debug(f"Negeren: Ad '{url}' reeds geanalyseerd en prijs niet gedaald.")
                    continue
                    
                title = ad.get("title", "")
                description = ad.get("description", "")
                img_url = ad.get("image_url")
                
                # ========== WOORDFILTER (0 API Kosten) ==========
                blacklisted_word = is_blacklisted(title, description)
                if blacklisted_word:
                    logger.info(f"🚫 [Filter] '{title}' geblokkeerd op woord: '{blacklisted_word}'. AI-scan overgeslagen.")
                    save_ad(url, price_float, 0.0, status="filtered")
                    continue
                
                # ========== PRIJS SANITY CHECK (0 API Kosten) ==========
                # Gebruik een grove schatting o.b.v. het zoekwoord om absurde prijzen 
                # te filteren VOORDAT we de AI inschakelen.
                rough_spot = 0.0
                gold_spot = spot_prices.get("gold_eur_oz_physical")
                silver_spot = spot_prices.get("silver_eur_oz_physical")
                
                if gold_spot:
                    kw_lower = keyword.lower()
                    if "tientje" in kw_lower or "10 g" in kw_lower:
                        rough_spot = gold_spot * 0.1947  # ~6g puur goud
                    elif "krugerrand" in kw_lower or "1 oz" in kw_lower or "maple" in kw_lower:
                        rough_spot = gold_spot  # 1 Oz
                    elif "10 gram" in kw_lower:
                        rough_spot = gold_spot * 0.3215  # 10g
                    elif "zilver" in kw_lower and silver_spot:
                        rough_spot = silver_spot
                
                if rough_spot > 0:
                    # < 25% van spot = vrijwel zeker oplichting of nep
                    if price_float < (rough_spot * 0.25):
                        logger.info(f"🚫 [Sanity] '{title}' (€{price_float}) < 25% van geschatte spot (€{rough_spot:.0f}). Scam filter.")
                        save_ad(url, price_float, 0.0, status="filtered_price_low")
                        continue
                    # > 120% van spot = te duur, geen arbitrage mogelijk
                    if price_float > (rough_spot * 1.20):
                        logger.info(f"💤 [Sanity] '{title}' (€{price_float}) > 120% van geschatte spot (€{rough_spot:.0f}). Te duur, overgeslagen.")
                        save_ad(url, price_float, 0.0, status="filtered_price_high")
                        continue
                
                # ========== HANDELAAR FILTER ==========
                # Voorheen werden 'pro' verkopers hard geblokkeerd. 
                # Op verzoek van de gebruiker (i.v.m. partijen zoals Muntbar) 
                # laten we de puur wiskundige 'Dynamische Marge' bepalen of de deal
                # goed genoeg is, in plaats van de verkoper op voorhand te blokkeren.
                seller_type = ad.get("seller_type", "particulier")
                if seller_type == "pro":
                    logger.debug(f"🏪 [Info] '{title}' is van een Pro/Bedrijf verkoper. Wordt toch geëvalueerd o.b.v. wiskunde.")

                # We hebben op z'n minst een richtprijs. Laten we hem door Pass 1 halen.
                if img_url and 'http' in img_url:
                    try:
                        resp = await asyncio.to_thread(requests.get, img_url, timeout=5)
                        if resp.status_code == 200:
                            # Sla tijdelijk op
                            os.makedirs("temp_cart", exist_ok=True)
                            tmp_path = f"temp_cart/radar_{hash(url)}.jpg"
                            with open(tmp_path, 'wb') as f:
                                f.write(resp.content)
                                
                            # Pre Scan met de Marktplaats titel als keiharde context voor de berekening
                            # SLEEP: Voorkom 429 Resource Exhausted op de gratis Gemini API Tier
                            await asyncio.sleep(5) 
                            
                            ad_context = f"Advertentie Titel: {title}\nBeschrijving: {ad.get('description', '')}"
                            pre_scan = await asyncio.to_thread(pre_scan_image, [tmp_path], text_context=ad_context)
                            metal = pre_scan.get("metaal", "Goud").lower()
                            weight = pre_scan.get("gewicht_oz", 1.0)
                            
                            if metal != "goud" and metal != "zilver":
                                continue
                                
                            # [LOGIC UPGRADE] AI Sanity Check & Self-Healing Loop
                            is_valid, sanity_err = validate_price_sanity(metal, price_float, weight)
                            if not is_valid:
                                logger.info(f"⚠️ [Healing Loop] Sanity Check gefaald ('{title}'): {sanity_err}")
                                # Self-Healing prompt
                                ad_context_heal = f"{ad_context}\nLET OP: De werkelijke vraagprijs op Marktplaats is €{price_float}. Het is extreem onwaarschijnlijk dat dit {weight} Oz is. Her-evalueer het exacte gewicht."
                                # Korte sleep voor Rate Limits
                                await asyncio.sleep(5)
                                pre_scan_healed = await asyncio.to_thread(pre_scan_image, [tmp_path], text_context=ad_context_heal)
                                metal = pre_scan_healed.get("metaal", "Goud").lower()
                                weight = pre_scan_healed.get("gewicht_oz", 1.0)
                                
                                # Laatste sanity check
                                is_valid_2, _ = validate_price_sanity(metal, price_float, weight)
                                if not is_valid_2:
                                    logger.info(f"🚫 [Sanity Blok] Na Healing faalt de ad nog. Scam of Data Error. Negeer.")
                                    save_ad(url, price_float, 0.0, status="filtered_sanity_failed")
                                    continue
                                else:
                                    logger.info(f"✨ [Sanity Healed] AI heeft gewicht met succes autonoom gecorrigeerd naar {weight} Oz.")
                                
                            # Bereken actuele prijzen (Ask & Bid)
                            dealer_data = await fetch_dealer_premiums(pre_scan)
                            d_ask, d_name_ask, _, d_method_ask = get_lowest_ask_price("Geanalyseerd Product", dealer_data)
                            d_bid, d_name_bid, _, d_method_bid = get_highest_bid_price("Geanalyseerd Product", dealer_data)
                            
                            # Bereken Spot Waarde (Harde Bodem)
                            spot_waarde = 0.0
                            gold_spot = spot_prices.get("gold_eur_oz_physical")
                            silver_spot = spot_prices.get("silver_eur_oz_physical")
                            
                            if metal == "goud" and gold_spot:
                                spot_waarde = weight * gold_spot
                            elif metal == "zilver" and silver_spot:
                                spot_waarde = weight * silver_spot
                            
                            # Registreer in SQLite: AI Analyse voltooid (ongeacht of het een deal is)
                            status_db = "scanned"
                            
                            # Logica: Als de Marktplaats prijs MEER dan 3% GOEDKOPER is dan de Dealer (Ask)
                            # OF de Marktplaats prijs onder Spot zit, sla Alarm.
                            
                            if d_ask > 0:
                                margin_vs_dealer = ((d_ask - price_float) / d_ask) * 100
                                
                                # Dynamische Marge o.b.v. producttype
                                required_margin = get_dynamic_margin(pre_scan, title)
                                
                                # Arbitrage Gevonden! 
                                if margin_vs_dealer > required_margin:
                                    status_db = "alerted"
                                    stat_deals += 1
                                    # Trigger uitgebreide alert
                                    await trigger_radar_alert(
                                        bot=context.bot, 
                                        chat_id=chat_id, 
                                        ad=ad, 
                                        pre_scan=pre_scan, 
                                        mp_price=price_float, 
                                        dealer_ask=d_ask, 
                                        dealer_ask_name=d_name_ask,
                                        dealer_ask_method=d_method_ask,
                                        dealer_bid=d_bid,
                                        dealer_bid_name=d_name_bid,
                                        dealer_bid_method=d_method_bid,
                                        spot_waarde=spot_waarde
                                    )
                            
                            # Opslaan in locale persistentie (zodat we nooit meer dezelfde API credits verspillen)
                            save_ad(url, price_float, spot_waarde, status=status_db)
                            stat_scanned += 1
                            stat_ai += 1
                                    
                    except Exception as e:
                        logger.error(f"Fout tijdens radar-analyse ad: {e}")
                        
        except Exception as e:
            logger.error(f"Fout in Radar Keyword '{keyword}': {e}")
            
    logger.info("📡 [Radar] Marktplaats scan afgerond.")
    log_radar_stats(scanned=stat_scanned, filtered=stat_filtered, ai_scanned=stat_ai, deals=stat_deals)

def calculate_deal_score(margin_pct):
    """Berekent een deal score van 1-5 sterren op basis van de marge."""
    if margin_pct >= 10:
        return "⭐⭐⭐⭐⭐"
    elif margin_pct >= 7:
        return "⭐⭐⭐⭐"
    elif margin_pct >= 5:
        return "⭐⭐⭐"
    elif margin_pct >= 4:
        return "⭐⭐"
    else:
        return "⭐"


async def trigger_radar_alert(bot, chat_id, ad, pre_scan, mp_price, dealer_ask, dealer_ask_name, dealer_ask_method, dealer_bid, dealer_bid_name, dealer_bid_method, spot_waarde):
    """Verstuurt de ultra-verrijkte interactieve hybride Telegram push incl Decision Triggers."""
    import re
    
    metal_icon = "🪙" if pre_scan.get("metaal", "").lower() == "goud" else "🥈"
    title = ad.get("title")
    url = ad.get("url")
    
    # Extract item ID for the callback
    item_id = "unknown"
    match = re.search(r'[ma](\d+)', url)
    if match:
        item_id = match.group(1)
        
    gew_oz = pre_scan.get("gewicht_oz", "Onbekend")
    prod_type = pre_scan.get("type", "Onbekend").capitalize()
    
    # --- 1 & 4. Spot & Scam Detectie ---
    spot_text = f"€{spot_waarde:.2f}" if spot_waarde > 0 else "Onbekend"
    scam_warning = ""
    if spot_waarde > 0 and mp_price < (spot_waarde * 0.95):
        scam_warning = "\n⚠️ *FRAUDERISICO:* Prijs ligt meer dan 5% onder de ruwe goudwaarde! Wees extreem voorzichtig (ophalen i.p.v. verzenden)."
    elif spot_waarde > 0 and mp_price < spot_waarde:
        spot_text += f" (Je koopt €{spot_waarde - mp_price:.2f} onder spot!)"
        
    # --- 2. Concurrentie (Ask) ---
    ask_margin = dealer_ask - mp_price
    
    # --- 3. Arbitrage Exit (Bid) ---
    flip_profit = dealer_bid - mp_price
    flip_text = f"€{dealer_bid:.2f} *(Directe Winst: +€{flip_profit:.2f})*" if flip_profit > 0 else f"€{dealer_bid:.2f} *(Verlies bij direct dumpen: €{flip_profit:.2f})*"
    if dealer_bid == 0:
        flip_text = "Geen data"
        
    # --- 5. Handmatig Tegenbod (Geparkeerde functionaliteit) ---
    # Auto-bidding faalt op AWS WAF (403 Forbidden). 
    # Optie C actief: Gebruiker klikt op de link, app opent, en hij biedt direct op zijn mobiel.
    
    # --- Bepaal Dealer Badges ---
    ask_badge = "[📡 Live]" if dealer_ask_method == "LIVE_SCRAPE" else "[🤖 Schatting]"
    bid_badge = "[📡 Live]" if dealer_bid_method == "LIVE_SCRAPE" else "[🤖 Schatting]"
    
    # --- Deal Score ---
    margin_pct = ((dealer_ask - mp_price) / dealer_ask * 100) if dealer_ask > 0 and mp_price > 0 else 0
    deal_score = calculate_deal_score(margin_pct)
    
    # --- Snelheidsbadge ---
    speed_badge = ""
    ad_date = ad.get("date", "")
    if ad_date and ("vandaag" in ad_date.lower() or "zojuist" in ad_date.lower() or "min" in ad_date.lower()):
        speed_badge = "\n⚡ *SNELLE VANGST!* Deze advertentie is zojuist geplaatst!"
    
    msg = (
        f"🚨 *Arbitrage Radar Alert* 🚨 {deal_score}\n{speed_badge}\n\n"
        f"⚖️ *Gewicht:* {gew_oz} Oz {pre_scan.get('metaal')} [{prod_type}] ({pre_scan.get('merk_of_muntnaam')})\n"
        f"📦 *Product:* {title}\n"
        f"{scam_warning}\n"
        f"💰 *Marktplaats Vraagprijs:* €{mp_price:.2f}\n"
        f"📉 *Spotwaarde (Smelt):* {spot_text}\n\n"
        f"🏛️ *Markt Vergelijking:*\n"
        f"🛒 *Goedkoopste Dealer ({dealer_ask_name}):* €{dealer_ask:.2f} {ask_badge} *(Besparing: €{ask_margin:.2f})*\n"
        f"🤝 *Beste Dealer Inkoop ({dealer_bid_name}):* {flip_text} {bid_badge}\n"
    )
    
    # Creëer het "Hybride" Interactive Keyboard (Puur navigatie)
    keyboard = [
        [InlineKeyboardButton("🔗 Bekijk Advertentie op MP", url=url)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Als er een foto is meegeleverd, sturen we die mee
    img_url = ad.get("image_url")
    if img_url:
        await bot.send_photo(chat_id=chat_id, photo=img_url, caption=msg, parse_mode="Markdown", reply_markup=reply_markup)
    else:
        await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown", reply_markup=reply_markup)
