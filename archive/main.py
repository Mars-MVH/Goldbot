import sys
import os

# Toevoegen van src aan python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from catalog import SILVER_PRODUCTS, GOLD_PRODUCTS
from pricing import get_live_spot_prices, calculate_intrinsic_value
from dealer_scraper import fetch_dealer_premiums, get_highest_bid_price, get_lowest_ask_price
from marktplaats_scraper import scrape_marktplaats_search

def main():
    print("=== Goud & Zilver Multi-Agent Systeem ===")
    print("Initialisatie Fase 1: Catalogus & Huidige Spotprijzen\n")
    
    print("[*] Het ophalen van actuele spotprijzen via Yahoo Finance (USD)...")
    try:
        spot_prices = get_live_spot_prices()
        # We gebruiken hier de fysieke variant voor de intrinsieke berekening, 
        # ook al is de premium momenteel 0 in het PoC model.
        gold_oz = spot_prices['gold_eur_oz_physical']
        silver_oz = spot_prices['silver_eur_oz_physical']
        
        print(f"✅ Goud Spotprijs (EUR/Fysiek): €{gold_oz:.2f} per Troy Ounce")
        print(f"✅ Zilver Spotprijs (EUR/Fysiek): €{silver_oz:.2f} per Troy Ounce\n")
        
        print("=== Waardeberekening Voorbeelden ===")
        # Voorbeeld 1: Zilveren Maple Leaf
        maple_leaf = SILVER_PRODUCTS["Maple Leaf"]
        maple_value = calculate_intrinsic_value(maple_leaf['weight_oz'], silver_oz)
        print(f"🪙 Zilveren Maple Leaf (1 Oz): Intrinsieke materiaalwaarde = €{maple_value:.2f}")

        # Voorbeeld 2: Gouden Krugerrand
        krugerrand = GOLD_PRODUCTS["Krugerrand"]
        krugerrand_value = calculate_intrinsic_value(krugerrand['weight_oz'], gold_oz)
        print(f"🟡 Gouden Krugerrand (1 Oz): Intrinsieke materiaalwaarde = €{krugerrand_value:.2f}")
        print("=== Dealer Premies & Inkoopprijzen (5 Dealers) ===")
        dealer_data = fetch_dealer_premiums()
        
        # We zoeken naar de absolute beste (hoogste) inkoopprijzen in de markt
        zilver_bid, zilver_dealer, zilver_country = get_highest_bid_price("Maple Leaf Zilver (1 Oz)", dealer_data)
        goud_bid, goud_dealer, goud_country = get_highest_bid_price("Krugerrand Goud (1 Oz)", dealer_data)
        
        print(f"🏆 Beste inkoopprijs Zilver (1 Oz): €{zilver_bid:.2f} bij {zilver_dealer} ({zilver_country})")
        print(f"🏆 Beste inkoopprijs Goud (1 Oz): €{goud_bid:.2f} bij {goud_dealer} ({goud_country})\n")
        
        # Voorbeeld 3: Dealer Spread Analyse
        for item_name, dealers in dealer_data.items():
            if "Zilver" in item_name:
                spot = silver_oz
            else:
                spot = gold_oz
                
            print(f"--- Overzicht voor {item_name} ---")
            for data in dealers:
                ask = data['ask_price']
                bid = data['bid_price']
                
                # De premie is het percentage dat de dealer bóven de spotprijs vraagt 
                premium_pct = ((ask - spot) / spot) * 100
                spread_pct = ((ask - bid) / bid) * 100
                
                print(f"🏬 {data['dealer_name']}: Aankoopprijs €{ask:.2f} | Inkoopprijs €{bid:.2f} (Spread: {spread_pct:.1f}%)")
            print()
            
        print("=== Marktplaats Arbitrage Scanner ===")
        # We zoeken naar de 'Zilveren Maple Leaf', zoals in het eerdere voorbeeld
        search_term = "Zilveren Maple Leaf"
        results = scrape_marktplaats_search(search_term, max_results=5)
        
        # Bepaal het metaaltype van de huidige zoekopdracht voor de juiste 'spot' vergelijking
        if "goud" in search_term.lower() or "krugerrand" in search_term.lower():
            aktuele_spot = gold_oz
            dealer_bid, dealer_bid_name, dealer_bid_country = get_highest_bid_price("Krugerrand Goud (1 Oz)", dealer_data)
            dealer_ask, dealer_ask_name, dealer_ask_country = get_lowest_ask_price("Krugerrand Goud (1 Oz)", dealer_data)
        else:
            aktuele_spot = silver_oz
            dealer_bid, dealer_bid_name, dealer_bid_country = get_highest_bid_price("Maple Leaf Zilver (1 Oz)", dealer_data)
            dealer_ask, dealer_ask_name, dealer_ask_country = get_lowest_ask_price("Maple Leaf Zilver (1 Oz)", dealer_data)
        
        if not results:
            print("Geen resultaten gevonden of scraping faalde.")
        
        from marktplaats_session import chat_with_seller, get_stealth_session
        from expert_agent import analyze_listing_with_expert
        
        # Haal de actieve sessie op voor mogelijke chats
        active_session = get_stealth_session()
        
        for item in results:
            print(f"Verkoper biedt aan: '{item['title']}'")
            print(f" - Prijs: {item['price_raw']} | URL: {item['url']}")
            
            is_buy_opportunity = False
            
            # Controleer of de prijs bruikbaar is voor rekenwerk
            if item['price_float'] is not None:
                vrg_prijs = item['price_float']
                
                VERZENDKOSTEN = 0.00 if dealer_ask_country == "NL" else 15.00 # NL ophalen of verzenden, BE/DE pakketpost
                omweg_str = " (Lokaal ophalen NL)" if VERZENDKOSTEN == 0 else f" (Post uit {dealer_ask_country})"
                
                # Arbitrage check (Vergelijking met GOEDKOOPSTE WEBSHOP incl. verzenden)
                dealer_totaalprijs = dealer_ask + VERZENDKOSTEN
                
                if vrg_prijs < dealer_totaalprijs:
                    besparing = dealer_totaalprijs - vrg_prijs
                    print(f"   ✅ KANS! Marktplaats (€{vrg_prijs:.2f}) is €{besparing:.2f} GOEDKOPER dan {dealer_ask_name} (€{dealer_totaalprijs:.2f} incl. €{VERZENDKOSTEN:.2f} porto{omweg_str}).")
                    is_buy_opportunity = True
                    
                    if vrg_prijs < dealer_bid:
                        winst = dealer_bid - vrg_prijs
                        print(f"   🚨 INSTANT ARBITRAGE! Ook nog eens €{winst:.2f} winst bij directe doorverkoop aan opkopers.")
                else:
                    te_duur = vrg_prijs - dealer_totaalprijs
                    print(f"   ❌ PASS: Koop dit nieuw bij {dealer_ask_name}. Je bespaart daar €{te_duur:.2f} {omweg_str} en hebt 100% nieuwheidsgarantie.")
            else:
                print(f"   ℹ️ Bieden / N.v.t - Prijs nader overeen te komen. (Expert controleert potentie)")
                is_buy_opportunity = True
                
            financial_context = None
            if item['price_float'] is not None and aktuele_spot > 0:
                mp_prijs = item['price_float']
                mp_premium_pct = ((mp_prijs - aktuele_spot) / aktuele_spot) * 100
                dealer_premium_pct = ((dealer_ask - aktuele_spot) / aktuele_spot) * 100
                
                financial_context = {
                    "spot_prijs": aktuele_spot,
                    "mp_prijs": mp_prijs,
                    "mp_premium_pct": mp_premium_pct,
                    "dealer_ask": dealer_ask,
                    "dealer_premium_pct": dealer_premium_pct
                }
                
            # ROEP DE EXPERT AAN
            if item.get("image_url"):
                expert_oordeel = analyze_listing_with_expert(item['title'], item.get("description", ""), item['image_url'], financial_context)
                print(f"   🧑‍💼 30-jarige Expert Oordeel: {expert_oordeel['expert_advice']}")
                if "extracted_details" in expert_oordeel:
                    print(f"      - Details uit omschrijving: {expert_oordeel['extracted_details']}")
                if "liquidity_and_tax_warning" in expert_oordeel:
                    print(f"      - Liquiditeit & Fiskaal: {expert_oordeel['liquidity_and_tax_warning']}")
                if "dealer_comparison" in expert_oordeel:
                    print(f"      - Dealer Vergelijking (Marktplaats vs Geautoriseerde Verkoper): {expert_oordeel['dealer_comparison']}")
                print(f"      - Conditie (Numismatisch): {expert_oordeel.get('condition_grading', 'Onbekend')}")
                print(f"      - Risico: {expert_oordeel.get('authenticity_risk', 'Onbekend')}")
                
                # Controleer of het een webshop betreft
                is_webshop = expert_oordeel.get('is_webshop_listing', False)
                if is_webshop:
                    print("   [🏪] Detectie: Dit is een commerciële webshop/dealer. We sturen GEEN chatbericht.")
                    print("         -> Routeer deze URL eventueel naar de DealerMonitor Module in de toekomst.")
                else:
                    voorgestelde_vraag = expert_oordeel['questions_for_seller'][0] if expert_oordeel.get('questions_for_seller') else None
                    if voorgestelde_vraag:
                        print(f"      - Voorgestelde Vraag: {voorgestelde_vraag}")
                        
                    # AUTONOOM BERICHTEN STUREN ALS HET EEN KANS IS (EN GEEN WEBSHOP)
                    if is_buy_opportunity and voorgestelde_vraag:
                        # Filter op hoog risico om te voorkomen dat we scammers berichten
                        if "Hoog" not in expert_oordeel['authenticity_risk']:
                            chat_with_seller(active_session, item['url'], voorgestelde_vraag)
                        else:
                            print("   [⚠️] Risico wegens authenticiteit te hoog. Bericht geannuleerd.")
                
            print("-" * 40)
            
    except Exception as e:
        print(f"❌ Fout bij ophalen prijzen: {e}")
        print("Installeer packages via: pip install -r requirements.txt")

if __name__ == "__main__":
    main()
