import sys
import os
import asyncio
from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))
from marktplaats_daemon import trigger_radar_alert
from telegram.ext import ApplicationBuilder

load_dotenv()

async def mock_radar_alert():
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    admin_chat_id = os.environ.get("ADMIN_CHAT_ID")
    
    app = ApplicationBuilder().token(telegram_token).build()
    
    # Fake Add Data
    mock_ad = {
        "title": "Gouden Tientje 1912 - Prachtige Kwaliteit",
        "url": "https://www.marktplaats.nl/v/verzamelen/munten/m200000000-gouden-tientje",
        "image_url": "https://www.thesilvermountain.nl/media/catalog/product/cache/1/image/1000x1000/9df78eab33525d08d6e5fb8d27136e95/g/o/gouden-tientje-willemina.jpg"
    }
    
    mock_pre_scan = {
        "metaal": "Goud",
        "gewicht_oz": 0.1947,
        "merk_of_muntnaam": "Gouden Tientje"
    }
    
    print("Verstuur Mock Alert naar Telegram...")
    await trigger_radar_alert(
        bot=app.bot,
        chat_id=admin_chat_id,
        ad=mock_ad,
        pre_scan=mock_pre_scan,
        mp_price=410.00,
        dealer_ask=445.50,
        dealer_ask_name="The Silver Mountain",
        dealer_ask_method="LIVE_SCRAPE",
        dealer_bid=425.00,
        dealer_bid_name="Holland Gold",
        dealer_bid_method="LIVE_SCRAPE",
        spot_waarde=412.35
    )
    print("Succesvol verzonden!")

if __name__ == "__main__":
    asyncio.run(mock_radar_alert())
