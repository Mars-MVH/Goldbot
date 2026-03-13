import os
import sys
from dotenv import load_dotenv
import asyncio

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from pricing import get_live_spot_prices
from dealer_scraper import fetch_dealer_premiums, get_lowest_ask_price, get_highest_live_bid_for_item
from macro_agent import fetch_macro_data
from charting import generate_price_chart

def run_simulation():
    print("🚀 Start E2E Simulatie van Module Componenten...\n")
    
    # 1. Pricing Module
    print("[1] Testen Pricing Module...")
    spot = get_live_spot_prices()
    print(f"    ✅ Spot Prices (Goud EUR): €{spot.get('gold_eur_oz_physical', 0):.2f}\n")
    
    # 2. Fake a Pre-Scan Result (Testing Year +/-2 Fallback by asking for 2018. 101 Munten only has 2017 and 2019, so it should fallback!)
    pre_scan_mock = {"metaal": "Zilver", "type": "Munt", "gewicht_oz": 1.0, "merk_of_muntnaam": "Maple Leaf", "jaartal": "2018"}
    
    # 3. Dealer Scraper
    print("[2] Testen Dealer Scraper Module (Apples to Apples)...")
    dealers = asyncio.run(fetch_dealer_premiums(pre_scan_mock))
    
    print("    📊 Overzicht Geanalyseerd Product (2026 Zilveren Krugerrand):")
    for d in dealers.get("Geanalyseerd Product", []):
         print(f"        - {d['dealer_name']} (€{d['ask_price']}) -> Method: {d['method']}")
         
    ask_price, dealer_name, country, method = get_lowest_ask_price("Geanalyseerd Product", dealers)
    print(f"\n    ✅ Laagste Prijs: €{ask_price:.2f} bij {dealer_name} ({method})\n")
    
    # 4. Macro Agent
    print("[3] Testen Macro Agent...")
    macro = fetch_macro_data()
    print(f"    ✅ DXY Huidig: {macro.get('dxy', {}).get('huidige_waarde')}\n")
    
    # 5. Charting
    print("\n[4] Testen Charting Module...")
    chart_path = generate_price_chart(days=7, metal="Gold")
    print(f"    ✅ Chart gegenereerd op: {chart_path}\n")
    
    # 6. Test Live Bids
    print("[5] Testen Liquidatiewaarde (Inkoop)...")
    bid_price, best_dealer = asyncio.run(get_highest_live_bid_for_item(pre_scan_mock, spot))
    print(f"    ✅ Hoogste bod voor {pre_scan_mock['merk_of_muntnaam']}: €{bid_price:.2f} bij {best_dealer}\n")
    
    print("🎉 Alle modules simuleren succesvol zonder errors!")

if __name__ == "__main__":
    run_simulation()
