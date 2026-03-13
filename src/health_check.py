import os
from telegram import Bot
from dealer_scraper import get_live_holland_gold, get_live_tsm, get_live_101munten
from dotenv import load_dotenv

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))
from marktplaats_scraper import scrape_marktplaats_search


async def _send_alert(chat_id, error_msg):
    """Helper: stuur een Telegram alert."""
    try:
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if bot_token and chat_id:
            bot = Bot(token=bot_token)
            await bot.send_message(chat_id=chat_id, text=error_msg, parse_mode="Markdown")
            print(f"📤 [Health Check] Alert verstuurd naar {chat_id}.")
    except Exception as tg_e:
        print(f"❌ [Health Check] Kon alert niet sturen: {tg_e}")


async def run_dealer_health_check(chat_id=None):
    """
    Controleert alle 3 live dealers: Holland Gold, TSM, 101 Munten.
    Stuurt Telegram alert als er scrapers offline gaan.
    """
    print("🩺 [Health Check] Start periodieke controle op alle Dealer Scrapers...")
    
    failures = []
    
    # 1. Holland Gold (4 waarden: gold, silver, gold_bar, silver_bar)
    try:
        hg_gold, hg_silv, hg_gold_bar, hg_silv_bar = get_live_holland_gold()
        if not hg_gold or not hg_silv or not hg_gold_bar:
            failures.append("Holland Gold: Goud/Zilver/Goudbaar gaf None terug")
        else:
            print(f"✅ [HC] Holland Gold OK: Goud €{hg_gold:.0f} | Zilver €{hg_silv:.0f}")
    except Exception as e:
        failures.append(f"Holland Gold: {e}")
    
    # 2. The Silver Mountain (3 waarden: silver_munt, gold, silver_bar)
    try:
        tsm_silv, tsm_gold, tsm_gold_bar, tsm_bar = get_live_tsm()
        if not tsm_silv and not tsm_gold:
            failures.append("TSM: Zowel zilver als goud gaf None terug")
        else:
            print(f"✅ [HC] TSM OK: Zilver €{tsm_silv or '?'} | Goud €{tsm_gold or '?'}")
    except Exception as e:
        failures.append(f"TSM: {e}")
    
    # 3. 101 Munten (3 waarden: gold, silver, silver_bar)
    try:
        m101_gold, m101_silv, m101_gold_bar, m101_bar = get_live_101munten()
        if not m101_gold and not m101_silv:
            failures.append("101 Munten: Zowel goud als zilver gaf None terug")
        else:
            print(f"✅ [HC] 101 Munten OK: Goud €{m101_gold or '?'} | Zilver €{m101_silv or '?'}")
    except Exception as e:
        failures.append(f"101 Munten: {e}")
    
    # Rapport
    if failures:
        fail_list = "\n".join(f"• {f}" for f in failures)
        error_msg = f"⚠️ *DEALER SCRAPER ALERT* ⚠️\n\n{len(failures)} van 3 scrapers gefaald:\n{fail_list}\n\nBot valt terug op algoritmisch model voor deze dealers."
        print(f"❌ [Health Check] {len(failures)} scraper(s) gefaald")
        await _send_alert(chat_id, error_msg)
        return False
    
    print("✅ [Health Check] Alle 3 dealer scrapers online!")
    return True


async def run_marktplaats_health_check(chat_id=None):
    """
    Simuleert een lichte zoekopdracht op Marktplaats om te valideren of:
    1. Cloudflare/Datadome de request niet direct blokkeert.
    2. De HTML tags (zoals .hz-Listing of mp-Listing) niet stiekem gewijzigd zijn.
    """
    print("🩺 [Health Check] Start periodieke controle op de Marktplaats Scraper...")
    
    try:
        results = scrape_marktplaats_search("goud", max_results=5)
        
        if not results or len(results) == 0:
            raise Exception("0 zoekresultaten. Mogelijk design-wijziging MP.")
            
        valid_prices = [r for r in results if r.get('price_float') and r.get('price_float') > 0]
        if not valid_prices:
             raise Exception("Prijzen niet leesbaar. Regex/Class mogelijk defect.")
             
        print("✅ [Health Check] Marktplaats Scraper OK.")
        return True
        
    except Exception as e:
        print(f"❌ [MP Health Check] Gefaald: {e}")
        error_msg = f"⚠️ *MP RADAR ALERT* ⚠️\n\nMarktplaats Radar defect!\n{e}\n\nControleer marktplaats_scraper.py classes of cookies."
        await _send_alert(chat_id, error_msg)
        return False
