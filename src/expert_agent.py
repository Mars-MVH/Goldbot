import json
import os
import requests
from io import BytesIO
from dotenv import load_dotenv
from gemini_limiter import QuotaExhaustedError
from ai_router import router_generate_content

# Laad environment variabelen (.env file)
load_dotenv()

EXPERT_BUYER_PROMPT = """
Jij bent een expert in fysieke edelmetaalhandel. Analyseer deze advertentie namens een KOPER.

REGELS:
- Elk JSON-veld: MAX 1-2 zinnen. Wees telegram-bondig.
- [📡 Live] = actuele webshopprijs. [🤖 Schatting] = algoritmisch berekend. Vermeld dit verschil.
- Kijk ALLEEN naar wat op de foto staat. Verzin niets.
- Bij collectibles/coinbars: premium van 18-30% boven spot is normaal.
- Negeer het irrelevante metaal (goud vs zilver).

Geef EXACT dit JSON formaat:
{
    "intentie": "Koop",
    "product": "Metaal + gewicht + type (bijv: Zilveren Coinbar 100g)",
    "analyse_koop": {
        "btw_valstrik": "MAX 1 zin. BTW-risico? Margeregeling? Bijv: 'Muntbaar = margeregeling, geen BTW-risico.'",
        "advies": "MAX 2 zinnen. Buy/No-Buy + waarom + alternatief."
    }
}
Houd je strikt aan deze JSON output. Genereer GEEN markdown formatting block rond de JSON.
"""

EXPERT_SELLER_PROMPT = """
Jij bent een expert in fysieke edelmetaalhandel. Analyseer deze uiting namens een VERKOPER.

REGELS:
- Elk JSON-veld: MAX 1-2 zinnen. Wees telegram-bondig.
- [📡 Live] = actuele prijs. [🤖 Schatting] = algoritmisch. Vermeld dit.
- Kijk ALLEEN naar wat op de foto staat. Verzin niets.
- Negeer het irrelevante metaal.

Geef EXACT dit JSON formaat:
{
    "intentie": "Verkoop",
    "product": "Metaal + gewicht + type (bijv: Gouden Baar 20g)",
    "analyse_verkoop": {
        "reele_waarde": "MAX 1 zin. Minimumprijs op basis van dealer-inkoop.",
        "advies": "MAX 1 zin. Accepteren / Onderhandelen / Afwijzen + waarom.",
        "betere_opties": "MAX 1 zin. Waar krijg je meer? Bijv: 'TSM biedt €X [📡].'"
    }
}
Houd je strikt aan deze JSON output. Genereer GEEN markdown formatting block rond de JSON.
"""

PASS_1_SYSTEM_PROMPT = """
Jij bent een formidabele data-extractor voor edelmetalen. Je taak is supersnel: Bekijk de meegeleverde afbeelding(en) en retourneer DIRECT feitelijke classificatie-data in JSON. 
Kijk naar visuele gravures op de munt of baar (bijv. '1/4 Oz', '50g', 'C. Hafner', 'Umicore'). 
Wees feitelijk over de conditie: zie je krassen of beschadigingen? Zie je een origineel blistercertificaat of originele capsule?

Geef ALTIJD EXACT de volgende JSON structuur:
{
    "metaal": "Goud of Zilver of Platina",
    "type": "Munt of Baar of Coinbar",
    "gewicht_oz": "Het exacte gewicht PER STUK vertaald naar Troy Ounces. Bijv. een 50g baar is 1.607 Oz. Een 100g baar is 3.215 Oz. Een 1/4 munt is 0.25 Oz. NOOIT vermenigvuldigen met aantal stuks! Altijd het gewicht van 1 enkel exemplaar. (Nummer)",
    "merk_of_muntnaam": "Bijv. 'C. Hafner' of 'Krugerrand'",
    "product_subtype": "plain of collectible of limited_edition of numismatic. 'plain' = standaard bullion bar/munt zonder extra design. 'collectible' = design bars, coinbars, special editions met artistiek ontwerp, laser-engraving, uniek serienummer. 'limited_edition' = gelimiteerde oplage. 'numismatic' = historische of zeldzame munten.",
    "jaartal": "Jaartal, of 'Onbekend'",
    "conditie_opmerkingen": "Kort (bijv. 'Zware krassen zichtbaar' of 'In nieuwstaat')",
    "verpakking": "Bijv. 'In assay certificaat' of 'Losse munt zonder capsule'",
    "vraagprijs_uit_tekst": "Als er een prijs wordt genoemd in de tekst/foto (bijv. '€325' of '325 euro'), vul deze in als getal (bijv. 325). Anders: null"
}
"""

def pre_scan_image(image_paths, text_context=""):
    """
    Fase 15 (Pass 1): Snelle visuele classificatie van het product voordat we prijzen berekenen.
    """
    print(f"👁️ [Pass 1] Start Visuele Pre-Scan op {len(image_paths)} foto's...")
    
    try:
        # Prompt voorbereiden
        prompt = "Bekijk de afbeelding(en) en retourneer DIRECT feitelijke classificatie-data in JSON."
        if text_context:
            prompt += f"\n\nContext:\n{text_context}"
            
        # Router aanroepen (Vision model focus)
        data = router_generate_content(
            prompt=prompt,
            images=image_paths,
            system_instruction=PASS_1_SYSTEM_PROMPT,
            model_override="moondream" # Voor Ollama switch
        )
        
        # Robust Weight Parsing
        raw_weight = data.get("gewicht_oz", 1.0)
        try:
            if isinstance(raw_weight, str):
                import re
                clean_w = re.sub(r'[^\d.]', '', raw_weight.replace(',', '.'))
                data["gewicht_oz"] = float(clean_w) if clean_w else 1.0
            else:
                data["gewicht_oz"] = float(raw_weight)
        except:
             data["gewicht_oz"] = 1.0
             
        print(f"👁️ [Pass 1] Resultaat: {data}")
        return data

    except Exception as e:
        print(f"❌ [Pass 1] Fout tijdens Pre-Scan: {e}")
        # Bepaal intelligente fallback o.b.v. text
        fallback_type = "Munt" if text_context and "munt" in text_context.lower() else "Baar"
        fallback_gew = 1.0
        
        if text_context:
            import re
            tc_lower = text_context.lower()
            if "tientje" in tc_lower or "10 gulden" in tc_lower:
                fallback_gew = 0.1947
                fallback_type = "Munt"
            elif "krugerrand" in tc_lower:
                fallback_gew = 1.0
                fallback_type = "Munt"
            else:
                m_gram = re.search(r'(\d+)\s*(?:gram|g\b)', tc_lower)
                if m_gram:
                     fallback_gew = float(m_gram.group(1)) * 0.03215
                     fallback_type = "Baar"
                     
        return {"metaal": "Goud", "type": fallback_type, "gewicht_oz": fallback_gew, "merk_of_muntnaam": "Fallback", "conditie_opmerkingen": "Analyse faalde"}



def analyze_whatsapp_offer(text_content, image_paths, market_prices_str, mode="Koop", classification=None):
    """
    Specifieke handler voor WhatsApp Aanbiedingen.
    """
    print(f"🧠 [Expert AI] Inspecteert WhatsApp aanbieding met {len(image_paths)} foto's. (Modus: {mode})")
    
    try:
        # Prompt voorbereiden
        context_str = f"\n\n--- FINANCIËLE CONTEXT ---\n{market_prices_str}\n" \
                      f"Vergelijk de vraagprijs met deze dealer/spot prijzen."

        sys_prompt = EXPERT_BUYER_PROMPT if mode == "Koop" else EXPERT_SELLER_PROMPT
        prompt = f"De tekst van de aanbieding/bod is:\n{text_content}{context_str}"
        
        # Router aanroepen
        return router_generate_content(
            prompt=prompt,
            images=image_paths,
            system_instruction=sys_prompt
        )

    except Exception as e:
        print(f"❌ [Expert AI] Fout tijdens analyse via Router: {e}")
        return get_mock_response(mode)

def get_mock_response(mode="Koop"):
    if mode == "Koop":
        return {
            "intentie": "Koop",
            "product": "Zilver, 1 Oz",
            "huidige_marktprijs": "Spot: 30, Dealer Ask: 35",
            "analyse_koop": {
                "vraagprijs_oordeel": "Goed",
                "btw_valstrik": "Geen (munt)",
                "macro_impact": "Gunstig",
                "advies": "Mooie kans, de marktplaats prijs is significant goedkoper dan de dealer."
            }
        }
    else:
        return {
            "intentie": "Verkoop",
            "product": "Zilver, 1 Oz",
            "huidige_marktprijs": "Spot: 30, Dealer Bid: 31",
            "analyse_verkoop": {
                "jouw_vraagprijs_premium": "N.v.t. (Alleen bod ontvangen)",
                "bod_van_koper": "30",
                "ideale_vraagprijs_advies": "Vraag 33, ligt mooi in het midden.",
                "reele_waarde": "32",
                "advies": "Afwijzen",
                "betere_opties": "Verkoop aan The Silver Mountain voor 31"
            }
        }

