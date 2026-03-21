import os
import sys
import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from dotenv import load_dotenv
import asyncio
import datetime
import pytz
from health_check import run_dealer_health_check, run_marktplaats_health_check
from marktplaats_daemon import run_marktplaats_radar
from dealer_scraper import fetch_dealer_premiums, get_lowest_ask_price, get_highest_bid_price, get_top_3_ask, get_top_3_bid, get_cached_dealer_premiums, get_highest_live_bid_for_item, calibrate_dealer_premiums, DEALER_PROFILES
from expert_agent import analyze_whatsapp_offer, pre_scan_image
from pricing import get_live_spot_prices, get_gold_volatility, check_flash_dip, validate_price_sanity
from gemini_limiter import get_quota_status
from database import get_today_stats, get_week_stats, add_portfolio_item, get_portfolio, remove_portfolio_item
from macro_agent import fetch_macro_data, analyze_macro_sentiment, fetch_reddit_sentiment, get_upcoming_events
from cme_scraper import CMEScraper
from charting import generate_price_chart

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# In-memory "Winkelmandje" per gebruiker (chat_id)
# Structuur: { chat_id: {"text": [], "photos": []} }
user_carts = {}

# In-memory cooldowns voor flash dip alerts (anti-spam)
last_flash_dip_alert = {"gold": 0.0, "silver": 0.0}

async def handle_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Vangt klikken op InlineKeyboards op."""
    query = update.callback_query
    try:
        await query.answer()
    except Exception as e:
        print(f"[Callback Warning] Kon query.answer() niet uitvoeren: {e}")
    
    data = query.data
    # Handle kluis item deletion
    if data.startswith("del_kluis_"):
        try:
            item_id = int(data.split("_")[2])
            if remove_portfolio_item(item_id):
                await query.answer(f"✅ Item #{item_id} verwijderd!")
                await kluis_command(update, context)
            else:
                await query.answer(f"❌ Kon item niet verwijderen.", show_alert=True)
        except Exception as e:
            await query.answer(f"Fout: {e}")
        return
    
    # Handle kluis toevoegen wizard
    if data == "kluis_toevoegen":
        keyboard = [
            [InlineKeyboardButton("Krugerrand 1 Oz", callback_data="kluis_preset_Krugerrand_1")],
            [InlineKeyboardButton("Maple Leaf 1 Oz", callback_data="kluis_preset_Maple Leaf_1")],
            [InlineKeyboardButton("Goudbaar 1 Oz", callback_data="kluis_preset_Goudbaar_1")],
            [InlineKeyboardButton("Goudbaar 1/2 Oz", callback_data="kluis_preset_Goudbaar_0.5")],
            [InlineKeyboardButton("Goudbaar 100g", callback_data="kluis_preset_Goudbaar 100g_3.215")],
            [InlineKeyboardButton("Zilverbaar 1kg", callback_data="kluis_preset_Zilverbaar 1kg_32.15")],
            [InlineKeyboardButton("Philharmoniker 1 Oz", callback_data="kluis_preset_Philharmoniker_1")],
            [InlineKeyboardButton("📝 Handmatig invoeren", callback_data="kluis_manual")],
            [InlineKeyboardButton("🔙 Terug", callback_data="dashboard_kluis")],
        ]
        await query.message.edit_text(
            "➕ *Kluis Toevoegen*\n\nKies een product of voer handmatig in:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    if data == "kluis_manual":
        await query.message.edit_text(
            "📝 *Handmatig Toevoegen*\n\n"
            "Typ in de chat:\n"
            "`/kluis [aantal] [product] [gewicht_oz] [prijs]`\n\n"
            "Voorbeelden:\n"
            "• `/kluis 1 Krugerrand 1 2650`\n"
            "• `/kluis 3 Maple Leaf 1 2700`\n"
            "• `/kluis 1 Umicore Bar 0.5 1350`\n"
            "• `/kluis 2 Zilverbaar 1kg 32.15 980`\n\n"
            "_Tip: gebruik 0.5 voor 1/2 oz, 0.25 voor 1/4 oz_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Terug", callback_data="kluis_toevoegen")]])
        )
        return
    
    if data.startswith("kluis_preset_"):
        # Format: kluis_preset_ProductNaam_GewichtOz
        parts = data[len("kluis_preset_"):]
        last_underscore = parts.rfind("_")
        product_name = parts[:last_underscore]
        weight_oz = float(parts[last_underscore + 1:])
        
        # Sla op in user context voor de volgende stap
        context.user_data["kluis_pending"] = {
            "product": product_name,
            "weight_oz": weight_oz
        }
        
        keyboard = [
            [InlineKeyboardButton("1 stuk", callback_data="kluis_amount_1"),
             InlineKeyboardButton("2 stuks", callback_data="kluis_amount_2"),
             InlineKeyboardButton("5 stuks", callback_data="kluis_amount_5")],
            [InlineKeyboardButton("10 stuks", callback_data="kluis_amount_10"),
             InlineKeyboardButton("20 stuks", callback_data="kluis_amount_20")],
            [InlineKeyboardButton("🔙 Terug", callback_data="kluis_toevoegen")],
        ]
        await query.message.edit_text(
            f"📦 *{product_name}* ({weight_oz} Oz)\n\nHoeveel stuks?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    if data.startswith("kluis_amount_"):
        amount = int(data.split("_")[2])
        pending = context.user_data.get("kluis_pending", {})
        if not pending:
            await query.answer("❌ Geen product geselecteerd. Begin opnieuw.", show_alert=True)
            return
        
        pending["amount"] = amount
        context.user_data["kluis_pending"] = pending
        
        await query.message.edit_text(
            f"💰 *{amount}x {pending['product']}* ({pending['weight_oz']} Oz)\n\n"
            "Typ nu de *aankoopprijs per stuk* in euro's in de chat.\n"
            "Bijvoorbeeld: `2650` of `32.50`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuleer", callback_data="dashboard_kluis")]])
        )
        return

    # --- INLINE DASHBOARD ROUTING ---
    chat_id = update.effective_chat.id
    if data == "dashboard_koop":
        await analyse_command(update, context, mode="Koop")
    elif data == "dashboard_verkoop":
        await analyse_command(update, context, mode="Verkoop")
    elif data == "dashboard_premiums":
        await premiums_command(update, context)
    elif data == "dashboard_kluis":
        await kluis_command(update, context)
    elif data == "dashboard_week":
        await weekoverzicht_command(update, context)
    elif data == "dashboard_radar":
        await radar_command(update, context)
    elif data == "dashboard_home":
        welcome_msg = "✅ Je bent terug in het Hoofdmenu. Gebruik de vaste knoppen onderaan je scherm!"
        await query.message.edit_text(welcome_msg, parse_mode="Markdown", reply_markup=None)
    elif data == "dashboard_annuleer":
        user_carts[chat_id] = {"text": [], "photos": []}
        await query.message.reply_text("🚫 Actie geannuleerd. Het mandje is leeg.")
    
    return

def get_inline_dashboard():
    keyboard = [
        [InlineKeyboardButton("🟢 Analyse Koop", callback_data="dashboard_koop"), InlineKeyboardButton("🏷️ Analyse Verkoop", callback_data="dashboard_verkoop")],
        [InlineKeyboardButton("📊 Premiums & Ratio", callback_data="dashboard_premiums"), InlineKeyboardButton("🏦 Kluis", callback_data="dashboard_kluis")],
        [InlineKeyboardButton("📊 Weekoverzicht", callback_data="dashboard_week"), InlineKeyboardButton("📡 Radar", callback_data="dashboard_radar")],
        [InlineKeyboardButton("❌ Annuleer / Leeg Mandje", callback_data="dashboard_annuleer")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_main_keyboard():
    """Grote, persistente bot knoppen onderin het scherm."""
    keyboard = [
        ["🟢 Analyse Koop", "🏷️ Analyse Verkoop"],
        ["📊 Premiums & Ratio", "🏦 Kluis"],
        ["📊 Weekoverzicht", "📡 Radar"],
        ["❌ Annuleer / Leeg Mandje"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_carts[chat_id] = {"text": [], "photos": []}
    
    # BotCommands worden nu geregistreerd bij bot startup (post_init in main)
    
    
    welcome_msg = (
        "🤖 *Welkom bij de GoudBot (AI Expert)*\n\n"
        "Forward WhatsApp berichten (tekst en foto's) van dealers of kopers direct naar mij.\n"
        "Ik voeg ze toe aan je tijdelijke 'mandje'.\n\n"
        "👇 Druk op een van de *vaste actie-knoppen onderin je scherm* als je klaar bent!"
    )
    
    await context.bot.send_message(
        chat_id=chat_id, 
        text=welcome_msg, 
        parse_mode="Markdown", 
        reply_markup=get_main_keyboard()
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in user_carts:
        user_carts[chat_id] = {"text": [], "photos": []}
        
    text = update.message.text
    
    # [ROBUSTE FALLBACK] Menu keywords vangen
    if text and text.strip().lower() in ["menu", "home", "dashboard", "/menu", "/dashboard"]:
        await start_command(update, context)
        return

    # [KLUIS WIZARD] Vang prijsinvoer op als er een pending kluis-item is
    pending = context.user_data.get("kluis_pending") if hasattr(context, 'user_data') else None
    if pending and pending.get("amount") and text:
        clean_price = text.strip().replace(',', '.').replace('€', '').strip()
        try:
            price = float(clean_price)
            product = pending["product"]
            weight_oz = pending["weight_oz"]
            amount = pending["amount"]
            metal = "zilver" if any(x in product.lower() for x in [
                "zilver", "silver", "maple", "eagle", "philharmoniker", "britannia"
            ]) else "goud"
            
            is_valid, sanity_err = validate_price_sanity(metal, price, weight_oz)
            if not is_valid:
                await update.message.reply_text(
                    f"⚠️ *Sanity Check Gefaald*\n{sanity_err}",
                    parse_mode="Markdown"
                )
                return
            
            if add_portfolio_item(product, weight_oz, metal, price, amount=amount):
                # Wizard afgerond — opruimen
                del context.user_data["kluis_pending"]
                await update.message.reply_text(
                    f"✅ {amount}x *{product}* ({weight_oz} Oz) toegevoegd "
                    f"aan je kluis voor €{price:.0f} per stuk!",
                    parse_mode="Markdown"
                )
                # Ververs kluis overzicht
                context.args = []
                await kluis_command(update, context)
            else:
                await update.message.reply_text("❌ Fout bij opslaan. Probeer opnieuw.")
            return
        except ValueError:
            # Geen geldig getal — negeer wizard, ga door naar normale text handling
            pass

    # [ROBUSTE FALLBACK] Vang '/kluis' commando's af die door Telegram 
    # onterecht als text zijn bestempeld (door copy-pastes, spaties of forwards).
    if text and text.strip().lower().startswith("/kluis"):
        clean_text = text.strip()[6:].strip() # verwijder '/kluis'
        context.args = clean_text.split() if clean_text else []
        await kluis_command(update, context)
        return
    
    if text == "🟢 Analyse Koop":
        await analyse_command(update, context, mode="Koop")
        return
    elif text == "🏷️ Analyse Verkoop":
        await analyse_command(update, context, mode="Verkoop")
        return
    elif text == "📊 Premiums & Ratio":
        await premiums_command(update, context)
        return
    elif text == "🏦 Kluis":
        await kluis_command(update, context)
        return
    elif text == "📊 Weekoverzicht":
        await weekoverzicht_command(update, context)
        return
    elif text == "📡 Radar":
        await radar_command(update, context)
        return
    elif text == "❌ Annuleer / Leeg Mandje":
        user_carts[chat_id] = {"text": [], "photos": []}
        await update.message.reply_text("🚫 Actie geannuleerd. Het mandje is leeg.")
        return
        
    user_carts[chat_id]["text"].append(text)
    
    text_count = len(user_carts[chat_id]["text"])
    await update.message.reply_text(
        f"✅ Tekst toegevoegd aan mandje ({text_count} teksten geladen).\n\n👇 _Kies een actie in het menu onderaan je scherm._",
        parse_mode="Markdown"
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in user_carts:
        user_carts[chat_id] = {"text": [], "photos": []}
        
    # Pak de foto of het ongecomprimeerde document afb.
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    elif update.message.document:
        file_id = update.message.document.file_id
    else:
        return
        
    file = await context.bot.get_file(file_id)
    
    # Capture optionele caption
    caption = update.message.caption
    if not caption and update.message.text:
        caption = update.message.text
    if caption:
        user_carts[chat_id]["text"].append(caption)

    # Download foto lokaal in een temp map
    os.makedirs("temp_cart", exist_ok=True)
    file_path = f"temp_cart/{file_id}.jpg"
    await file.download_to_drive(file_path)
    
    user_carts[chat_id]["photos"].append(file_path)
    
    count = len(user_carts[chat_id]["photos"])
    
    # Voorkom keyboard spam bij een album/mediagroup (meerdere foto's tegelijk)
    media_group_id = update.message.media_group_id
    if media_group_id:
        if "processed_groups" not in context.chat_data:
            context.chat_data["processed_groups"] = set()
            
        if media_group_id in context.chat_data["processed_groups"]:
            # Foto is opgeslagen, maar we sturen niet N keer het menu.
            return
            
    # Het bottom-keyboard is al actief via /start. Geen extra reply_markup nodig.
    await update.message.reply_text(
        f"✅ Foto/Tekst toegevoegd aan mandje ({count} items).\n\n👇 _Kies een actie in het menu onderaan je scherm._",
        parse_mode="Markdown"
    )

# ============================================================
# Premium bereik per producttype (bron: IEX, Het Zilver Forum,
# professionele dealers, Reddit r/pmsforsale, Grok analyse)
# Gesplitst: goud (lage premiums) vs zilver (hogere premiums)
# ============================================================
PREMIUM_RANGES = {
    # --- GOUD munten ---
    "goud_krugerrand":     (3, 7,   "Gouden Krugerrand"),
    "goud_maple leaf":     (3, 7,   "Gouden Maple Leaf"),
    "goud_philharmoniker": (3, 7,   "Gouden Philharmoniker"),
    "goud_eagle":          (4, 8,   "American Gold Eagle"),
    "goud_kangaroo":       (3, 7,   "Gouden Kangaroo"),
    "goud_panda":          (5, 12,  "Gouden Panda"),
    "goud_sovereign":      (4, 10,  "Sovereign"),
    # --- GOUD baren ---
    "goud_baar":           (1, 5,   "Goudbaar"),
    "goud_bar":            (1, 5,   "Goudbaar"),
    # --- GOUD historisch ---
    "tientje":             (6, 15,  "Gouden Tientje"),
    "gulden":              (6, 15,  "Gulden"),
    "dukaat":              (6, 15,  "Dukaat"),
    # --- ZILVER munten ---
    "zilver_maple leaf":   (12, 22, "Zilveren Maple Leaf"),
    "zilver_eagle":        (15, 25, "Silver Eagle"),
    "zilver_philharmoniker": (12, 20, "Zilveren Philharmoniker"),
    "zilver_kangaroo":     (12, 20, "Zilveren Kangaroo"),
    "zilver_panda":        (18, 30, "Zilveren Panda"),
    # --- ZILVER baren ---
    "zilver_baar":         (10, 20, "Zilverbaar (plain)"),
    "zilver_bar":          (10, 20, "Zilverbaar (plain)"),
    # --- ZILVER collectible / design ---
    "zilver_collectible":  (18, 30, "Zilver Collectible/Design"),
    "zilver_coinbar":      (18, 30, "Zilver Coinbar"),
    "zilver_limited":      (20, 35, "Zilver Limited Edition"),
    # --- Generieke fallbacks ---
    "goud":                (3, 8,   "Goud (generiek)"),
    "zilver":              (12, 22, "Zilver (generiek)"),
}

def _get_premium_range(pre_scan_data):
    """Zoekt het normale premium-bereik voor dit producttype. Metaal-aware."""
    metaal = pre_scan_data.get('metaal', 'Goud').lower()
    merk = pre_scan_data.get('merk_of_muntnaam', '').lower()
    ptype = pre_scan_data.get('type', '').lower()
    subtype = pre_scan_data.get('product_subtype', 'plain').lower()
    
    # Stap 1: Check productsubtype (collectible/limited)
    if 'zilver' in metaal:
        if subtype in ('collectible', 'limited_edition'):
            return PREMIUM_RANGES.get(f"zilver_{subtype.split('_')[0]}", (18, 30, "Zilver Collectible/Design"))
        if 'coinbar' in ptype:
            return 18, 30, "Zilver Coinbar"
    
    # Stap 2: Zoek specifieke metaal+merk match
    prefix = "zilver" if "zilver" in metaal else "goud"
    search = f"{merk} {ptype}".lower()
    for key, (lo, hi, label) in PREMIUM_RANGES.items():
        if key.startswith(prefix + "_"):
            keyword = key.replace(prefix + "_", "")
            if keyword in search:
                return lo, hi, label
    
    # Stap 3: Generieke metaal fallback  
    if 'zilver' in metaal:
        if 'baar' in ptype or 'bar' in ptype:
            return 10, 20, "Zilverbaar (plain)"
        return 12, 22, "Zilver (generiek)"
    elif 'goud' in metaal:
        if 'baar' in ptype or 'bar' in ptype:
            return 1, 5, "Goudbaar"
        return 3, 8, "Goud (generiek)"
    
    return 3, 8, "Standaard Bullion"

def _premium_bar(pct, lo, hi):
    """Maakt een visuele premium-balk."""
    max_blocks = 10
    filled = min(max_blocks, max(0, int(pct / (hi * 1.5) * max_blocks)))
    bar = "█" * filled + "░" * (max_blocks - filled)
    if pct < lo:
        label = "⚠️ Verdacht laag"
    elif pct <= hi:
        label = "✅ Normaal"
    elif pct <= hi * 1.5:
        label = "⚠️ Duur"
    else:
        label = "🔴 Te duur"
    return f"[{bar}] {pct:.1f}%  ← {label} ({lo}-{hi}% = marktconform)"

def _sentiment_bar(score):
    """Maakt een visuele sentiment-balk van -100 tot +100."""
    max_blocks = 10
    normalized = (score + 100) / 20  # -100→0, 0→5, +100→10
    filled = min(max_blocks, max(0, int(normalized)))
    bar = "█" * filled + "░" * (max_blocks - filled)
    if score <= -50:
        label = "🔴 Bearish"
    elif score <= -20:
        label = "🟠 Licht bearish"
    elif score <= 20:
        label = "🟡 Neutraal"
    elif score <= 50:
        label = "🟢 Licht bullish"
    else:
        label = "🟢 Bullish"
    return f"[{bar}] {score:+d}  ← {label}"

def build_enhanced_analysis_header(mode, pre_scan_data, dyn_spot, dyn_ask, dyn_bid, 
                                    dyn_dealer_ask, dyn_dealer_bid, spot_prices, 
                                    dyn_premium_pct, gold_volatility_pct=0, vraagprijs=0):
    """
    Bouwt de verbeterde analyse-header: Verdict, Premium Thermometer,
    Rode Vlaggen, en Onderhandelingstip.
    vraagprijs = de prijs die de verkoper vraagt in de advertentie (0 = onbekend)
    """
    parts = []
    metaal = pre_scan_data.get("metaal", "Goud").lower()
    gewicht = pre_scan_data.get("gewicht_oz", 1.0)
    merk = pre_scan_data.get("merk_of_muntnaam", "Onbekend")
    zuiverheid = pre_scan_data.get("zuiverheid", "999")
    subtype = pre_scan_data.get("product_subtype", "plain").lower()
    
    # --- FIX 1: Gebruik vraagprijs voor premium als die beschikbaar is ---
    if vraagprijs > 0 and dyn_spot > 0:
        ad_premium_pct = ((vraagprijs - dyn_spot) / dyn_spot) * 100
    else:
        ad_premium_pct = dyn_premium_pct  # Fallback naar dealer premium
    
    # --- FIX 3: Spot validatie tegen dealer data ---
    if dyn_bid > 0 and dyn_spot > 0 and dyn_spot < dyn_bid * 0.9:
        print(f"⚠️ [Spot Check] Spot (€{dyn_spot:.2f}) is <90% van dealer-bid (€{dyn_bid:.2f}). Spot mogelijk onjuist!")
        parts.append("⚠️ _Spotprijs mogelijk niet actueel (weekend/nacht). Gebruik dealerprijzen als referentie._")
    
    # --- 1. VERDICT ---
    lo, hi, type_label = _get_premium_range(pre_scan_data)
    if mode == "Koop":
        if vraagprijs > 0 and dyn_spot > 0:
            # Vergelijk vraagprijs met dealer ask (de eerlijke vergelijking)
            if dyn_ask > 0:
                verschil_dealer_pct = ((dyn_ask - dyn_spot) / dyn_spot * 100) if dyn_spot > 0 else 0
                if ad_premium_pct < verschil_dealer_pct:
                    parts.append(f"🟢 *VERDICT: KOPEN* — €{vraagprijs:.0f} is {verschil_dealer_pct - ad_premium_pct:.1f}% goedkoper dan de webshop (€{dyn_ask:.0f}).")
                elif ad_premium_pct <= hi:
                    parts.append(f"🟢 *VERDICT: KOPEN* — Premium van {ad_premium_pct:.1f}% is binnen normaal bereik voor {type_label} ({lo}-{hi}%).")
                elif ad_premium_pct <= hi * 1.3:
                    parts.append(f"🟡 *VERDICT: ONDERHANDELEN* — Premium van {ad_premium_pct:.1f}% is aan de hoge kant voor {type_label} ({lo}-{hi}%). Probeer af te dingen.")
                else:
                    parts.append(f"🔴 *VERDICT: AFWIJZEN* — Premium van {ad_premium_pct:.1f}% is hoog voor {type_label} ({lo}-{hi}%).")
            else:
                if ad_premium_pct <= hi:
                    parts.append(f"🟢 *VERDICT: KOPEN* — Premium van {ad_premium_pct:.1f}% valt binnen {type_label} ({lo}-{hi}%).")
                else:
                    parts.append(f"🔴 *VERDICT: AFWIJZEN* — Premium van {ad_premium_pct:.1f}% is hoog voor {type_label} ({lo}-{hi}%).")
        elif dyn_ask > 0 and dyn_spot > 0:
            # Geen vraagprijs bekend — vergelijk dealer ask
            verschil_dealer = ((dyn_ask - dyn_spot) / dyn_ask * 100) if dyn_ask > 0 else 0
            if dyn_premium_pct < verschil_dealer:
                parts.append(f"🟢 *VERDICT: KOPEN* — {verschil_dealer - dyn_premium_pct:.1f}% goedkoper dan de goedkoopste webshop.")
            elif dyn_premium_pct < 2:
                parts.append(f"🟢 *VERDICT: KOPEN* — Premium van slechts {dyn_premium_pct:.1f}% is uitstekend.")
            else:
                parts.append(f"🔴 *VERDICT: AFWIJZEN* — Premium van {dyn_premium_pct:.1f}% is niet beter dan de webshop ({verschil_dealer:.1f}%).")
        else:
            parts.append("⚪ *VERDICT: ONVOLDOENDE DATA* — Kon spotwaarde niet bepalen.")
    else:
        # Verkoop: check of de aangeboden prijs boven dealer-inkoop ligt
        if dyn_bid > 0:
            pct_vs_bid = ((dyn_spot - dyn_bid) / dyn_bid * 100) if dyn_bid > 0 else 0
            parts.append(f"ℹ️ *VERKOOP ANALYSE* — Dealer-inkoop: €{dyn_bid:.2f} ({pct_vs_bid:+.1f}% vs spot)")
        else:
            parts.append("ℹ️ *VERKOOP ANALYSE*")
    
    # --- 2. PRODUCTINFO ---
    gewicht_gram = float(gewicht) * 31.1035 if gewicht else 0
    subtype_label = f" [{subtype.replace('_', ' ').title()}]" if subtype != "plain" else ""
    parts.append(
        f"\n⚖️ *Product:* {merk} {gewicht} Oz {pre_scan_data.get('metaal', 'Goud')} "
        f"[{pre_scan_data.get('type', 'Onbekend').capitalize()}]{subtype_label}"
        f"\n📏 Gewicht: {gewicht_gram:.1f}g | Zuiverheid: {zuiverheid}"
    )
    if vraagprijs > 0:
        parts.append(f"💰 Vraagprijs: €{vraagprijs:.0f} (premium: {ad_premium_pct:+.1f}% boven spot €{dyn_spot:.0f})")
    
    # --- 3. PREMIUM THERMOMETER ---
    bar = _premium_bar(ad_premium_pct, lo, hi)
    parts.append(f"\n📊 *Premium:* {bar}")
    
    # --- 3b. WEDERVERKOOP SPREAD ---
    if mode == "Koop" and dyn_bid > 0:
        koop_prijs = vraagprijs if vraagprijs > 0 else dyn_ask
        if koop_prijs > 0:
            verlies_eur = koop_prijs - dyn_bid
            verlies_pct = (verlies_eur / koop_prijs) * 100
            parts.append(
                f"🔄 *Wederverkoop:* Koop €{koop_prijs:.0f} → Inkoop €{dyn_bid:.0f} "
                f"(spread: -{verlies_pct:.1f}%  |  -€{verlies_eur:.0f})"
            )
    
    # --- 4. RODE VLAGGEN ---
    flags = []
    if dyn_spot > 0 and ad_premium_pct < -5:
        flags.append("🚨 Prijs ver onder spot — zeer waarschijnlijk nep/oplichting!")
    elif dyn_spot > 0 and ad_premium_pct < 0:
        flags.append("⚠️ Prijs onder spot — verdacht. Vraag foto keurmerk + weegfoto.")
    if not pre_scan_data.get("merk_of_muntnaam") or pre_scan_data.get("merk_of_muntnaam") == "Onbekend":
        flags.append("⚠️ Onbekend merk/munttype — moeilijker doorverkoopbaar, reken -5% waarde.")
    
    if flags:
        parts.append("\n" + "\n".join(flags))
    
    # --- 5. ONDERHANDELINGSTIP (kort) ---
    if mode == "Koop" and dyn_ask > 0 and dyn_bid > 0 and dyn_spot > 0:
        is_collectible = subtype in ('collectible', 'limited_edition', 'numismatic')
        if is_collectible:
            bied_prijs = dyn_ask * 0.92
            parts.append(f"\n💬 *Tip:* Bied €{bied_prijs:.0f} (8% onder dealer). Bij 2+ stuks: vraag extra korting.")
        else:
            parts.append(f"\n💬 *Tip:* Bied €{dyn_bid:.0f} (dealer-inkoop). Bij 2+ stuks: vraag 3-5% korting.")
    elif mode == "Verkoop" and dyn_bid > 0 and dyn_spot > 0:
        min_vraag = dyn_bid * 1.02
        parts.append(f"\n💬 *Tip:* Vraag min. €{min_vraag:.0f} particulier. Onder €{dyn_spot:.0f} (spot) → verkoop via dealer.")
    
    return "\n".join(parts)


async def analyse_command(update: Update, context: ContextTypes.DEFAULT_TYPE, mode="Koop"):
    chat_id = update.effective_chat.id
    message_obj = update.callback_query.message if update.callback_query else update.message
    
    if chat_id not in user_carts or (not user_carts[chat_id]["text"] and not user_carts[chat_id]["photos"]):
        await message_obj.reply_text("Je analyse-mandje is leeg. Forward eerst wat foto's en tekst.")
        return
        
    cart = user_carts[chat_id]
    num_photos = len(cart["photos"])
    num_texts = len(cart["text"])
    
    status_msg = await message_obj.reply_text(
        f"⏳ *[1/4] Afbeeldingen voorbereiden...*\n"
        f"Gevonden: {num_photos} foto's, {num_texts} teksten",
        parse_mode="Markdown"
    )
    
    # Imports moved to top of file
    
    try:
        # 1. Pass 1: Visuele Voor-Scan van het Product
        await status_msg.edit_text(
            "👁️ *[2/4] Visuele AI Scan bezig...*\n"
            "_De AI leest nu de graveerstempels en conditie (via de Gemini Enterprise Cloud)_",
            parse_mode="Markdown"
        )
        # Geef cart-tekst mee zodat pre-scan de vraagprijs en gewicht beter kan herkennen
        import asyncio
        cart_text_context = "\n".join(cart["text"]) if cart["text"] else ""
        
        # Voer de zware synchrone pre-scan uit in een aparte thread
        pre_scan_data = await asyncio.to_thread(pre_scan_image, cart["photos"], text_context=cart_text_context)
        metaal_type = pre_scan_data.get("metaal", "Goud").lower()
        
        # 2. Haal actuele prijzen & sentiment op (PARALLEL om tijd te besparen op de Pi)
        await status_msg.edit_text(
            "📊 *[3/4] Live marktprijzen & sentiment ophalen...*\n"
            "_Actuele data van goud/zilver dealers scrapen en macro-bot raadplegen..._",
            parse_mode="Markdown"
        )
        
        import asyncio
        
        # Start de taken parallel: Dealer scraping (Playwright), Spot API, en Macro AI
        spot_task = asyncio.to_thread(get_live_spot_prices)
        dealer_task = fetch_dealer_premiums(pre_scan_data)
        
        def _get_macro_sentiment_sync():
            mr = fetch_macro_data()
            rr = fetch_reddit_sentiment()
            er = get_upcoming_events()
            return analyze_macro_sentiment(mr, rr, er)
            
        macro_task = asyncio.to_thread(_get_macro_sentiment_sync)
        
        # Wacht tot Dealer & Spot Data binnen is (voor we marktprijzen berekenen)
        dealer_data, spot_prices = await asyncio.gather(dealer_task, spot_task)
        
        dyn_ask, dyn_dealer_ask, dyn_country_ask, dyn_ask_method = get_lowest_ask_price("Geanalyseerd Product", dealer_data)
        dyn_bid, dyn_dealer_bid, dyn_country_bid, dyn_bid_method = get_highest_bid_price("Geanalyseerd Product", dealer_data)
        
        gold_ask, gold_dealer_ask, gold_country_ask, g_ask_method = get_lowest_ask_price("Krugerrand Goud (1 Oz)", dealer_data)
        gb_ask, gb_dealer_ask, gb_country_ask, gb_ask_method = get_lowest_ask_price("Goudbaar (1 Oz)", dealer_data)
        silver_ask, silver_dealer_ask, silver_country_ask, s_ask_method = get_lowest_ask_price("Maple Leaf Zilver (1 Oz)", dealer_data)
        
        gold_bid, gold_dealer_bid, gold_country_bid, g_bid_method = get_highest_bid_price("Krugerrand Goud (1 Oz)", dealer_data)
        silver_bid, silver_dealer_bid, silver_country_bid, s_bid_method = get_highest_bid_price("Maple Leaf Zilver (1 Oz)", dealer_data)
        
        gold_premium = ((gold_ask - spot_prices['gold_eur_oz_physical']) / spot_prices['gold_eur_oz_physical']) * 100 if spot_prices['gold_eur_oz_physical'] else 0
        silver_premium = ((silver_ask - spot_prices['silver_eur_oz_physical']) / spot_prices['silver_eur_oz_physical']) * 100 if spot_prices['silver_eur_oz_physical'] else 0
        
        dyn_weight = float(pre_scan_data.get('gewicht_oz', 1.0)) if pre_scan_data else 1.0
        dyn_metal = pre_scan_data.get('metaal', 'Goud').lower() if pre_scan_data else 'goud'
        base_spot = spot_prices['gold_eur_oz_physical'] if 'goud' in dyn_metal else spot_prices['silver_eur_oz_physical']
        dyn_spot = base_spot * dyn_weight
        dyn_premium_pct = ((dyn_ask - dyn_spot) / dyn_spot) * 100 if dyn_spot > 0 else 0
        
        g_porto = 0.00 if gold_country_ask == "NL" else 15.00
        gb_porto = 0.00 if gb_country_ask == "NL" else 15.00
        s_porto = 0.00 if silver_country_ask == "NL" else 15.00
        dyn_porto = 0.00 if dyn_country_ask == "NL" else 15.00
        
        g_pickup = "(Lokaal Ophalen NL)" if g_porto == 0 else f"(Post {gold_country_ask})"
        gb_pickup = "(Lokaal Ophalen NL)" if gb_porto == 0 else f"(Post {gb_country_ask})"
        s_pickup = "(Lokaal Ophalen NL)" if s_porto == 0 else f"(Post {silver_country_ask})"
        dyn_pickup = "(Lokaal Ophalen NL)" if dyn_porto == 0 else f"(Post {dyn_country_ask})"
        
        # Format tags
        g_ask_tag = "📡 Live" if g_ask_method == "LIVE_SCRAPE" else "🤖 Schatting"
        gb_ask_tag = "📡 Live" if gb_ask_method == "LIVE_SCRAPE" else "🤖 Schatting"
        s_ask_tag = "📡 Live" if s_ask_method == "LIVE_SCRAPE" else "🤖 Schatting"
        g_bid_tag = "📡 Live" if g_bid_method == "LIVE_SCRAPE" else "🤖 Schatting"
        s_bid_tag = "📡 Live" if s_bid_method == "LIVE_SCRAPE" else "🤖 Schatting"
        dyn_ask_tag = "📡 Live" if dyn_ask_method == "LIVE_SCRAPE" else "🤖 Schatting"
        dyn_bid_tag = "📡 Live" if dyn_bid_method == "LIVE_SCRAPE" else "🤖 Schatting"
        
        dealer_urls = {
            "Holland Gold": "https://www.hollandgold.nl",
            "101 Munten": "https://www.101munten.nl",
            "Goud999": "https://www.goud999.com",
            "The Silver Mountain": "https://www.thesilvermountain.nl",
            "Goudstandaard": "https://www.europesegoudstandaard.be",
            "Inkoop Edelmetaal": "https://www.inkoopedelmetaal.nl",
            "Goudwisselkantoor": "https://www.goudwisselkantoor.nl",
            "Goudonline.nl": "https://www.goudonline.nl",
            "Goudmunter": "https://www.goudmunter.be",
            "Goldsilver.be": "https://www.goldsilver.be",
            "MP-Edelmetalle": "https://www.mp-edelmetalle.de",
            "Kettner Edelmetalle": "https://www.kettner-edelmetalle.de",
            "GoldRepublic": "https://www.goldrepublic.nl"
        }
        g_url = dealer_urls.get(gold_dealer_ask, "https://www.google.com/search?q=" + gold_dealer_ask.replace(" ", "+"))
        gb_url = dealer_urls.get(gb_dealer_ask, "https://www.google.com/search?q=" + gb_dealer_ask.replace(" ", "+"))
        s_url = dealer_urls.get(silver_dealer_ask, "https://www.google.com/search?q=" + silver_dealer_ask.replace(" ", "+"))
        
        # Dynamisch URL bouwen voor pre_scan item
        is_estimate = (dyn_ask_method == "ALGORITME")
        
        if is_estimate:
            # Drop the brand name to avoid matching a non-existent item at the dealer
            dyn_name = f"Vergelijkbare {pre_scan_data.get('gewicht_oz', '1')} Oz {pre_scan_data.get('type', '')}".strip()
            dyn_url_search = f"{dyn_dealer_ask} {pre_scan_data.get('gewicht_oz', '1')} Oz {pre_scan_data.get('type', '')}".replace(" ", "+")
        else:
            # Live Scrape: Use exact brand name
            dyn_name = f"{pre_scan_data.get('merk_of_muntnaam', '')} {pre_scan_data.get('gewicht_oz', '1')} Oz {pre_scan_data.get('type', '')}".strip()
            dyn_url_search = f"{dyn_dealer_ask} {dyn_name}".replace(" ", "+")
            
        dyn_url = dealer_urls.get(dyn_dealer_ask, "https://www.google.com/search?q=" + dyn_url_search)
        
        match_context = "Exacte Match" if not is_estimate else "Vergelijkbare Categorie Match"
        
        market_str = (
            f"🎯 *Specifieke Match (Pass 1 Analyse - {match_context})*:\n"
            f"• Gevonden referentie: {dyn_name}.\n"
            f"• Kale Spotwaarde voor exact dit gewicht: €{dyn_spot:.2f}\n"
            f"• Dealer Verkoop (Ask): €{dyn_ask:.2f} [+{dyn_premium_pct:.1f}% Premium] [{dyn_ask_tag}] bij {dyn_dealer_ask} [+ €{dyn_porto:.2f} {dyn_pickup}] | URL: {dyn_url}\n"
            f"• Dealer Inkoop (Bid): €{dyn_bid:.2f} [{dyn_bid_tag}] bij {dyn_dealer_bid}\n"
            f"\n"
            f"Goud Spotprijs: €{spot_prices['gold_eur_oz_physical']:.2f} per Oz\n"
            f"Goedkoopste gecontroleerde Goudbaar Dealer (Ask): €{gb_ask:.2f} [{gb_ask_tag}] bij {gb_dealer_ask} [+ €{gb_porto:.2f} {gb_pickup}] | URL: {gb_url}\n"
            f"Goedkoopste gecontroleerde Goudmunt Dealer (Ask): €{gold_ask:.2f} [{g_ask_tag}] bij {gold_dealer_ask} [+ €{g_porto:.2f} {g_pickup}] | URL: {g_url}\n"
            f"Beste Goud Dealer Inkoopprijs (Bid/Cash baren en munten): €{gold_bid:.2f} [{g_bid_tag}] bij {gold_dealer_bid} ({gold_country_bid})\n\n"
            f"Zilver Spotprijs: €{spot_prices['silver_eur_oz_physical']:.2f} per Oz\n"
            f"Goedkoopste gecontroleerde Zilver Dealer (Ask): €{silver_ask:.2f} [{s_ask_tag}] bij {silver_dealer_ask} [+ €{s_porto:.2f} {s_pickup}] | URL: {s_url}\n"
            f"Beste Zilver Dealer Inkoopprijs (Bid/Cash): €{silver_bid:.2f} [{s_bid_tag}] bij {silver_dealer_bid} ({silver_country_bid})\n\n"
            f"LET OP AAN DE EXPERT: Gebruik de Prijzen onder 'Specifieke Match' voor je absolute kernadvies. Gebruik de algemene 1 Oz prijzen puur als brede marktcontext. Benoem ALTIJD letterlijk de naam EN de URL/Link van de specifieke dealer in jouw antwoordtekst!"
        )
        
        # 3. Combineer alle verzamelde tekst en voeg de Pre-Scan JSON toe voor Pass 2
        combined_text = "\n".join(cart["text"])
        if not combined_text:
            combined_text = "Geen tekst bijgeleverd."
            
        combined_text += f"\n\n--- PRE-SCAN RESULTAAT (100% FEITELIJK) ---\n"
        combined_text += f"Metaal: {pre_scan_data.get('metaal', 'Onbekend')}\n"
        combined_text += f"Type: {pre_scan_data.get('type', 'Onbekend')}\n"
        combined_text += f"Gewicht (Oz): {pre_scan_data.get('gewicht_oz', 'Onbekend')}\n"
        combined_text += f"Merk: {pre_scan_data.get('merk_of_muntnaam', 'Onbekend')}\n"
        combined_text += f"Jaartal: {pre_scan_data.get('jaartal', 'Onbekend')}\n"
        combined_text += f"Conditie: {pre_scan_data.get('conditie_opmerkingen', 'Onbekend')}\n"
        combined_text += f"Verpakking: {pre_scan_data.get('verpakking', 'Onbekend')}\n"
            
        # 4. Wacht tot de Macro achtergrondtaak ook klaar is (vaak is deze nu al af door caching/threading)
        macro_sentiment = await macro_task
            
        # 5. Roep de Gemini Expert aan (Pass 2)
        await status_msg.edit_text(
            "🧠 *[4/4] Expert Analyse schrijven...*\n"
            "_Het financiële aankoop/verkoop advies wordt nu gegenereerd..._",
            parse_mode="Markdown"
        )
        # Voer de zware synchrone tekst-analyse uit in een aparte thread
        expert_oordeel = await asyncio.to_thread(analyze_whatsapp_offer, combined_text, cart["photos"], market_str, mode=mode)
        
        # 5b. Extract vraagprijs uit pre-scan of tekst
        vraagprijs = 0
        try:
            vp_raw = pre_scan_data.get("vraagprijs_uit_tekst")
            if vp_raw is not None:
                vraagprijs = float(vp_raw)
        except (ValueError, TypeError):
            pass
        
        # Fallback: zoek prijs in cart tekst met regex
        if vraagprijs == 0 and cart["text"]:
            import re
            for txt in cart["text"]:
                # Zoek patronen als "€325", "325 euro", "EUR 325", "prijs 325"
                matches = re.findall(r'€\s*(\d+[\.,]?\d*)|(\d+[\.,]?\d*)\s*(?:euro|eur|EUR)', txt)
                for m in matches:
                    val = m[0] or m[1]
                    val = val.replace(',', '.')
                    try:
                        candidate = float(val)
                        if 10 < candidate < 100000:  # Sanity check
                            vraagprijs = candidate
                            break
                    except ValueError:
                        continue
                if vraagprijs > 0:
                    break
        
        if vraagprijs > 0:
            print(f"💰 [Analyse] Vraagprijs uit advertentie: €{vraagprijs:.0f}")
        
        # 6. Bouw de verbeterde analyse-header (Verdict, Thermometer, Tips)
        analysis_header = build_enhanced_analysis_header(
            mode=mode,
            pre_scan_data=pre_scan_data,
            dyn_spot=dyn_spot,
            dyn_ask=dyn_ask,
            dyn_bid=dyn_bid,
            dyn_dealer_ask=dyn_dealer_ask,
            dyn_dealer_bid=dyn_dealer_bid,
            spot_prices=spot_prices,
            dyn_premium_pct=dyn_premium_pct,
            vraagprijs=vraagprijs,
        )
        
        # 7. Formatteer de output netjes voor Telegram
        if mode == "Koop" and "analyse_koop" in expert_oordeel:
            analyse = expert_oordeel["analyse_koop"]
            reply_msg = (
                f"{analysis_header}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🧑‍💼 *AI Expert*\n"
                f"⚖️ {analyse.get('btw_valstrik', 'Geen BTW info')}\n"
                f"💎 {analyse.get('advies', 'Geen advies')}\n"
            )
        elif mode == "Verkoop" and "analyse_verkoop" in expert_oordeel:
            analyse = expert_oordeel["analyse_verkoop"]
            reply_msg = (
                f"{analysis_header}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🧑‍💼 *AI Expert*\n"
                f"⚖️ {analyse.get('reele_waarde', 'Onbekend')}\n"
                f"🏦 {analyse.get('betere_opties', 'Geen tips')}\n"
            )
        else:
            reply_msg = f"{analysis_header}\n\n🧑‍💼 *Expert* (Ruwe Output)\n{expert_oordeel}\n"
        
        # --- Goud-Zilver Ratio ---
        gz_ratio = ""
        if spot_prices['gold_eur_oz_physical'] > 0 and spot_prices['silver_eur_oz_physical'] > 0:
            ratio = spot_prices['gold_eur_oz_physical'] / spot_prices['silver_eur_oz_physical']
            gz_ratio = f" | G/Z ratio: {ratio:.0f}:1"
        
        # --- Dealer vergelijking (mode-afhankelijk) ---
        reply_msg += f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        reply_msg += f"📈 *Markt:* Goud €{spot_prices['gold_eur_oz_physical']:.2f} | Zilver €{spot_prices['silver_eur_oz_physical']:.2f}{gz_ratio}\n\n"
        
        if mode == "Koop":
            top3 = get_top_3_ask("Geanalyseerd Product", dealer_data)
            reply_msg += f"🎯 *Top-3 dealers (vgl. product, incl. verzending):*\n"
            for i, (price, name, country, method, shipping) in enumerate(top3, 1):
                flag = "🇳🇱" if country == "NL" else "🇧🇪" if country == "BE" else "🇩🇪"
                tag = "📡" if method == "LIVE_SCRAPE" else "🤖"
                total = price + shipping
                prem_pct = ((total - dyn_spot) / dyn_spot * 100) if dyn_spot > 0 else 0
                url = dealer_urls.get(name, "")
                link = f"[{name}]({url})" if url else name
                ship_note = f" _+€{shipping:.0f} verz._" if shipping > 0 else ""
                reply_msg += f"  {i}. {flag} {link}: €{total:.0f} (+{prem_pct:.0f}%) {tag}{ship_note}\n"
        else:
            top3_bid = get_top_3_bid("Geanalyseerd Product", dealer_data)
            reply_msg += f"💰 *Top-3 inkoop (vgl. product):*\n"
            for i, (price, name, country, method) in enumerate(top3_bid, 1):
                flag = "🇳🇱" if country == "NL" else "🇧🇪" if country == "BE" else "🇩🇪"
                tag = "📡" if method == "LIVE_SCRAPE" else "🤖"
                pct_vs_spot = ((price - dyn_spot) / dyn_spot * 100) if dyn_spot > 0 else 0
                reply_msg += f"  {i}. {flag} {name}: €{price:.0f} ({pct_vs_spot:+.0f}%) {tag}\n"
        
        # --- Sentiment (met sectietitel + labels) ---
        reply_msg += (
            f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🧠 *Macro & Sentiment*\n"
            f"{_sentiment_bar(macro_sentiment.get('macro_score', 0))}\n"
            f"_{macro_sentiment.get('advies_samenvatting', 'Onbekend')}_\n"
            f"📰 Socials: {macro_sentiment.get('sentiment_alert', 'Geen bijzonderheden')}\n"
            f"📅 Kalender: {macro_sentiment.get('kalender_alert', 'Geen aankomende events')}\n"
        )
        
        # Bepaal het metaaltype voor de grafiek (Goud is default)
        product_naam = expert_oordeel.get('product', 'Onbekend').lower()
        metal_for_chart = "Silver" if "zilver" in product_naam or "silver" in product_naam else "Gold"
        
        chart_path = generate_price_chart(days=30, metal=metal_for_chart)
        
        if chart_path and os.path.exists(chart_path):
            with open(chart_path, 'rb') as chart_photo:
                await context.bot.send_photo(chat_id=chat_id, photo=chart_photo, caption=f"📉 30-Dagen {metal_for_chart} Trend")
            os.remove(chart_path) # Direct opruimen
        else:
            reply_msg += "\n\n⚠️ *Grafiek Fout:* Kon actuele koersdata niet ophalen."
            
        try:
            await status_msg.delete()
        except:
            pass
            
        await message_obj.reply_text(reply_msg, parse_mode="Markdown", disable_web_page_preview=True)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        await message_obj.reply_text(f"❌ Oeps, er is iets misgegaan tijdens de analyse: {str(e)}")
        
    finally:
        # Opruimen van lokale foto's
        for photo_path in cart["photos"]:
            try:
                if os.path.exists(photo_path):
                    os.remove(photo_path)
            except Exception:
                pass
                
        # Na analyse, reset mandje en herstel menu
        user_carts[chat_id] = {"text": [], "photos": []}
        await context.bot.send_message(chat_id=chat_id, text="🧹 Mandje is geleegd voor de volgende deal.", reply_markup=get_inline_dashboard())

async def radar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handmatig triggeren van een radar-ronde (voor testen of ongeduld)"""
    chat_id = update.effective_chat.id
    msg_obj = update.message or update.callback_query.message
    await msg_obj.reply_text("📡 Radar geactiveerd: Zoeken naar arbitrage deals op Marktplaats...")
    
    # Gebruik een dummy context object om de chat_id door te geven aan de radar-run
    from collections import namedtuple
    DummyContext = namedtuple("DummyContext", ["bot", "job"])
    DummyJob = namedtuple("DummyJob", ["data"])
    dummy_ctx = DummyContext(bot=context.bot, job=DummyJob(data={'chat_id': chat_id}))
    
    await run_marktplaats_radar(dummy_ctx)
    await msg_obj.reply_text("📡 Radar cyclus voltooid.")

async def quota_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toont het huidige Gemini API quota verbruik."""
    q = get_quota_status()
    bar_len = 20
    filled = int(bar_len * q['calls_today'] / q['max_daily'])
    bar = '█' * filled + '░' * (bar_len - filled)
    
    msg = (
        f"📊 *Gemini API Quota Status*\n\n"
        f"Vandaag verbruikt: *{q['calls_today']}* / {q['max_daily']}\n"
        f"Resterend: *{q['remaining']}* calls\n"
        f"`[{bar}]` {q['percentage_used']}%"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def kluis_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Portfolio Kluis: /kluis [product] [gewicht_oz] [prijs] of /kluis (toon overzicht)"""
    args = getattr(context, 'args', None) or []
    
    if not args:
        # Toon portfolio
        items = get_portfolio()
        msg_obj = update.effective_message
        
        if not items:
            keyboard = [
                [InlineKeyboardButton("➕ Toevoegen", callback_data="kluis_toevoegen")],
                [InlineKeyboardButton("🔙 Terug naar Dashboard", callback_data="dashboard_home")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            empty_msg = "🏦 Je kluis is leeg.\n\nDruk op *➕ Toevoegen* om je eerste item toe te voegen!"
            if update.callback_query:
                await update.callback_query.message.edit_text(empty_msg, parse_mode="Markdown", reply_markup=reply_markup)
            else:
                await msg_obj.reply_text(empty_msg, parse_mode="Markdown", reply_markup=reply_markup)
            return
        
        if update.callback_query:
            try:
                await update.callback_query.answer("⏳ Prijzen ophalen...", show_alert=False)
            except Exception:
                pass
            status_msg = update.callback_query.message
        else:
            status_msg = await msg_obj.reply_text("⏳ *Momentje...* Ik haal realtime de actuele Inkoopprijzen (Liquidatiewaarde) op bij de dealers...", parse_mode="Markdown")
        
        total_cost = 0
        total_value = 0
        lines = []
        
        # Haal spotprijzen EENMAAL op voor alle items (performance fix)
        spot_prices = get_live_spot_prices()
        
        for item_id, product, weight_oz, metal, purchase_price, purchase_date, amount in items:
            # Formuleer Apples-to-Apples pre_scan object
            # Uitgebreide munt-detectie voor correcte categorisatie
            munt_keywords = [
                "munt", "krugerrand", "maple", "eagle", "philharmoniker",
                "britannia", "kangaroo", "kangaroe", "panda", "sovereign",
                "wildlife", "koala", "kookaburra", "buffalo", "libertad",
                "vienna", "lunar", "noah", "arche", "coinbar"
            ]
            product_lower = product.lower()
            is_munt = any(kw in product_lower for kw in munt_keywords)
            
            pre_scan_data = {
                "metaal": metal.lower(), 
                "type": "munt" if is_munt else "baar", 
                "gewicht_oz": weight_oz,
                "merk_of_muntnaam": product.replace(" (1 Oz)", "").replace(" (1kg)", "").strip(),
                "jaartal": "diverse"
            }
            
            highest_bid, best_dealer = await get_highest_live_bid_for_item(pre_scan_data, spot_prices)
            method = "LIVE_SCRAPE" if "Inkoop" in best_dealer else "ALGO"
            
            # Fallback als scraper/algo compleet failt
            if highest_bid == 0.0:
                 spot = spot_prices.get("gold_eur_oz_physical", 0) if "goud" in metal.lower() else spot_prices.get("silver_eur_oz_physical", 0)
                 highest_bid = spot * weight_oz
                 method = "SPOT_FALLBACK"
            
            # Highest_bid is for 1 item.
            current_value_per_item = highest_bid
                
            purchase_total = purchase_price * amount
            current_total = current_value_per_item * amount
                
            profit = current_total - purchase_total
            pct = (profit / purchase_total * 100) if purchase_total > 0 else 0
            emoji = "🟢" if profit >= 0 else "🔴"
            # [LOGIC UPGRADE] Spread Warning Check
            spread_warning = ""
            spot_m = spot_prices.get("gold_eur_oz_physical", 0) if "goud" in metal.lower() else spot_prices.get("silver_eur_oz_physical", 0)
            if spot_m > 0 and highest_bid > 0:
                spread = (spot_m * weight_oz - highest_bid) / (spot_m * weight_oz)
                if spread >= 0.10: # >10% inkoop spread t.o.v. spotwaarde
                    spread_warning = "\n      ⚠️ _Extreem hoge dealer spread (slechte inkoopprijs momenteel)!_"
            
            tag = "📡 Live" if method == "LIVE_SCRAPE" else "🤖 Algo"
            
            lines.append(f"{emoji} `#{item_id}` [{amount}x] *{product}* ({weight_oz} Oz)\n      Aankoop: \u20ac{purchase_total:.0f} ({amount}x \u20ac{purchase_price:.0f}) \u2014 Nu: \u20ac{current_total:.0f} ({pct:+.1f}%) \n      _Beste koper: {best_dealer} ({tag})_{spread_warning}")
            total_cost += purchase_total
            total_value += current_total
        
        total_profit = total_value - total_cost
        total_pct = (total_profit / total_cost * 100) if total_cost > 0 else 0
        total_emoji = "🟢" if total_profit >= 0 else "🔴"
        
        msg = (
            f"🏦 *Mijn Portfolio Kluis*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            + "\n\n".join(lines)
            + f"\n━━━━━━━━━━━━━━━━━━\n💰 *Liquidatiewaarde:* \u20ac{total_value:.0f}\n{total_emoji} *Totaal Rendement:* \u20ac{total_profit:+.0f} ({total_pct:+.1f}%)\n"
            f"\nℹ\ufe0f _Prijzen zijn gebaseerd op de actuele inkoopprijs bij dealers, niet grafiek-spot._"
        )
        
        # [UI UPGRADE] Inline Keyboards voor directe verwijdering
        inline_keyboard = []
        for item in items:
            item_id = item[0]
            product = item[1]
            inline_keyboard.append([InlineKeyboardButton(f"❌ Verwijder: {product}", callback_data=f"del_kluis_{item_id}")])
            
        inline_keyboard.append([InlineKeyboardButton("➕ Toevoegen", callback_data="kluis_toevoegen")])
        inline_keyboard.append([InlineKeyboardButton("🔙 Terug naar Dashboard", callback_data="dashboard_home")])
            
        reply_markup = InlineKeyboardMarkup(inline_keyboard)
        
        await status_msg.edit_text(msg, parse_mode="Markdown", reply_markup=reply_markup)
        return
    
    # Verwijder item
    if args[0].lower() == "verwijder" and len(args) >= 2:
        try:
            item_id = int(args[1])
            if remove_portfolio_item(item_id):
                await update.message.reply_text(f"\u2705 Item #{item_id} verwijderd uit je kluis.")
            else:
                await update.message.reply_text(f"\u274c Item #{item_id} niet gevonden.")
        except ValueError:
            await update.message.reply_text("Gebruik: `/kluis verwijder [id]`", parse_mode="Markdown")
        return
    
    # Toevoegen: /kluis [Aantal] Product GewichtOz PrijsPerStuk
    if len(args) >= 3:
        try:
            amount = 1
            start_idx = 0
            if args[0].isdigit():
                amount = int(args[0])
                start_idx = 1
                
            price_str = args[-1].replace(',', '.')
            weight_str = args[-2].replace(',', '.')
            # Ondersteuning voor breuknotatie (1/2, 1/4, 1/10)
            if '/' in weight_str:
                try:
                    num, den = weight_str.split('/')
                    weight_oz = float(num) / float(den)
                except (ValueError, ZeroDivisionError):
                    weight_oz = float(weight_str)
            else:
                weight_oz = float(weight_str)
            price = float(price_str)
            product = " ".join(args[start_idx:-2])
            
            metal = "zilver" if any(x in product.lower() for x in ["zilver", "silver", "maple", "eagle", "philharmoniker", "britannia"]) else "goud"
            
            # [LOGIC UPGRADE] AI Sanity & Typo Checker
            is_valid, sanity_err = validate_price_sanity(metal, price, weight_oz)
            if not is_valid:
                await update.message.reply_text(f"⚠️ *Sanity Check Gefaald*\n{sanity_err}", parse_mode="Markdown")
                return
                
            if add_portfolio_item(product, weight_oz, metal, price, amount=amount):
                await update.message.reply_text(f"\u2705 {amount}x *{product}* ({weight_oz} Oz) toegevoegd aan je kluis voor \u20ac{price:.0f} per stuk!", parse_mode="Markdown")
                # Ververs kluis overzicht
                context.args = []
                await kluis_command(update, context)
            else:
                await update.message.reply_text("\u274c Fout bij opslaan. Probeer opnieuw.")
        except ValueError:
            await update.message.reply_text("Gebruik: `/kluis [Aantal] Product GewichtOz PrijsPerStuk`\nBijv: `/kluis 5 Maple Leaf 1 32.50`", parse_mode="Markdown")
    else:
        await update.message.reply_text("Gebruik: `/kluis [Aantal] Product GewichtOz PrijsPerStuk`\nBijv: `/kluis 5 Maple Leaf 1 32.50`", parse_mode="Markdown")

async def weekoverzicht_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toont het weekoverzicht met radar statistieken."""
    s = get_week_stats()
    q = get_quota_status()
    msg_obj = update.message or update.callback_query.message
    
    msg = (
        f"📊 *Weekoverzicht (afgelopen 7 dagen)*\n\n"
        f"🔍 Gescand: *{s['scanned']}* advertenties\n"
        f"🚫 Gefilterd: *{s['filtered']}* (spam/te duur/blacklist)\n"
        f"🤖 AI geanalyseerd: *{s['ai_scanned']}*\n"
        f"🎯 Deals gevonden: *{s['deals']}*\n\n"
        f"💳 API Quota vandaag: {q['calls_today']}/{q['max_daily']} ({q['percentage_used']}%)\n"
    )
    await msg_obj.reply_text(msg, parse_mode="Markdown")

async def kalibreer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command om handmatig het zelflerende inkoop-algo te triggeren"""
    chat_id = update.effective_chat.id
    ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")
    if str(chat_id) != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔️ Alleen de admin mag deze bot kalibreren.")
        return
        
    await update.message.reply_text("🤖 *Start iteratie Zelflerend Algo...*\nIk ga nu actuele inkoopprijzen scrapen bij de dealers en het weegmodel updaten. Momentje aub...", parse_mode="Markdown")
    
    spot_prices = get_live_spot_prices()
    success = await calibrate_dealer_premiums(spot_prices)
    
    if success:
        # Maak ovezicht van de nieuwe marges
        from dealer_scraper import DEALER_PROFILES
        msg = "🎯 *Kalibratie Succesvol!*\nIn-memory `DEALER_PROFILES` zijn geüpdatet.\n\n"
        for d in DEALER_PROFILES[:2]: # Toon alleen top 2 om niet te overspoelen
            msg += f"*{d['name']}*\n"
            msg += f"• Zilver Munt: +{d['bid_premiums'].get('zilver_munt', 0)}%\n"
            msg += f"• Zilver Baar: +{d['bid_premiums'].get('zilver_baar', 0)}%\n"
            msg += f"• Goud Munt: {d['bid_premiums'].get('goud_munt', 0)}%\n\n"
            
        await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        await update.message.reply_text("⚠️ *Kalibratie Mislukt*\nBekijk de console logs voor meer details.", parse_mode="Markdown")

async def premiums_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toont de actuele Goud/Zilver ratio en Premium Heatmap van live dealers."""
    msg_obj = update.message or update.callback_query.message
    await msg_obj.reply_text("📊 Live premiums en G/Z ratio ophalen...")
    
    spot_prices = get_live_spot_prices()
    spot_gold = spot_prices.get('gold_eur_oz_physical', 0)
    spot_silver = spot_prices.get('silver_eur_oz_physical', 0)
    
    if not spot_gold or not spot_silver:
        await msg_obj.reply_text("❌ Kon live spotprijzen niet ophalen.")
        return
        
    gsr = spot_gold / spot_silver
    gsr_status = "🟢 Zilver is historisch goedkoop" if gsr >= 80 else "🔴 Goud is relatief goedkoop" if gsr < 60 else "🟡 Neutraal (60-80)"
    
    msg = f"⚖️ *Goud/Zilver Ratio*\nRatio: *{gsr:.1f}:1* ({gsr_status})\n\n"
    
    # Haal dealer data op voor heatmap comparison
    dealer_data = await fetch_dealer_premiums()
    
    products = [
        ("Krugerrand Goud (1 Oz)", spot_gold),
        ("Maple Leaf Zilver (1 Oz)", spot_silver),
        ("Goudbaar (1 Oz)", spot_gold),
        ("Zilverbaar (1kg)", spot_silver * 32.15)
    ]
    
    msg += "🔥 *Live Premium Heatmap (Alleen NL)*\n"
    
    for product, base_price in products:
        offers = dealer_data.get(product, [])
        live_offers = [o for o in offers if o["method"] == "LIVE_SCRAPE"]
        if not live_offers:
            continue
            
        live_offers.sort(key=lambda x: x["ask_price"])
        
        msg += f"\n*{product} (Spot: €{base_price:.0f}):*\n"
        for i, offer in enumerate(live_offers):
            price = offer["ask_price"]
            prem_pct = ((price - base_price) / base_price) * 100
            
            if i == 0:
                emoji = "🟢"
            elif i == len(live_offers) - 1 and len(live_offers) > 1:
                emoji = "🔴"
            else:
                emoji = "🟡"
                
            msg += f"{emoji} {offer['dealer_name']}: €{price:.0f} (+{prem_pct:.1f}%)\n"
            
    await msg_obj.reply_text(msg, parse_mode="Markdown")

def main():
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not telegram_token:
        print("WAARSCHUWING: TELEGRAM_BOT_TOKEN is niet ingesteld in de .env file!")
        return
        
    application = ApplicationBuilder().token(telegram_token).build()
    
    # [NATIVE TELEGRAM MENU] Registreer BotCommands bij opstarten
    async def post_init(app):
        """Wordt aangeroepen na het starten van de bot."""
        try:
            from telegram import BotCommand
            commands = [
                BotCommand("start", "Start de bot & open dashboard"),
                BotCommand("menu", "Open het Hoofdmenu"),
                BotCommand("kluis", "Bekijk je Portfolio Kluis"),
                BotCommand("radar", "Bekijk Marktplaats Radar status"),
                BotCommand("premiums", "Live Goud/Zilver Premiums"),
                BotCommand("weekoverzicht", "Bekijk weekstatistieken"),
                BotCommand("kalibreer", "Kalibreer dealer premiums (Admin only)"),
            ]
            await app.bot.set_my_commands(commands)
            print("[*] BotCommands menu succesvol geregistreerd.")
        except Exception as e:
            print(f"[Warning] set_my_commands() gefaald: {e}")
    
    application.post_init = post_init
    
    application.add_handler(CommandHandler('start', start_command))
    application.add_handler(CommandHandler('menu', start_command))
    application.add_handler(CommandHandler('analyse', analyse_command))
    application.add_handler(CommandHandler('radar', radar_command))
    application.add_handler(CommandHandler('quota', quota_command))
    application.add_handler(CommandHandler('kluis', kluis_command))
    application.add_handler(CommandHandler('weekoverzicht', weekoverzicht_command))
    application.add_handler(CommandHandler('premiums', premiums_command))
    application.add_handler(CommandHandler("kalibreer", kalibreer_command))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))
    application.add_handler(CallbackQueryHandler(handle_button_callback))
    
    print("[*] Telegram Bot draait en is klaar om WhatsApp forwards te ontvangen! (Druk Ctrl+C om te stoppen)")
    
    # Haal de admin chat_id op uit de .env voor error meldingen
    admin_chat_id = os.environ.get("ADMIN_CHAT_ID")
    
    # Wrapper function voor de JobQueue
    async def scheduled_health_check(context: ContextTypes.DEFAULT_TYPE):
        chat_id = context.job.data.get('chat_id') if context.job and context.job.data else admin_chat_id
        await run_dealer_health_check(chat_id=chat_id)
        # Auto-cleanup temp_cart (bestanden ouder dan 30 dagen)
        try:
            import time as _time
            cart_dir = os.path.join(os.path.dirname(__file__), '..', 'temp_cart')
            if os.path.isdir(cart_dir):
                now = _time.time()
                for f in os.listdir(cart_dir):
                    fp = os.path.join(cart_dir, f)
                    if os.path.isfile(fp) and (now - os.path.getmtime(fp)) > 30 * 86400:
                        os.remove(fp)
                        print(f"🧹 [Cleanup] Verwijderd: {f} (>30 dagen oud)")
        except Exception as cleanup_err:
            print(f"⚠️ [Cleanup] temp_cart opruiming gefaald: {cleanup_err}")
        
    async def scheduled_mp_health_check(context: ContextTypes.DEFAULT_TYPE):
        chat_id = context.job.data.get('chat_id') if context.job and context.job.data else admin_chat_id
        await run_marktplaats_health_check(chat_id=chat_id)

    # Voeg de job toe aan de ingebouwde JobQueue van de bot
    if application.job_queue:
        amsterdam_tz = pytz.timezone('Europe/Amsterdam')
        target_time = datetime.time(hour=8, minute=0, tzinfo=amsterdam_tz)
        
        # Draai elke dag om 08:00
        application.job_queue.run_daily(
            scheduled_health_check,
            time=target_time,
            data={'chat_id': admin_chat_id}
        )
        
        application.job_queue.run_daily(
            scheduled_mp_health_check,
            time=target_time,
            data={'chat_id': admin_chat_id}
        )
        
        # --- Autonome Radar (Crisis Mode: 5 min, Normaal: 15 min) ---
        async def dynamic_radar_job(context: ContextTypes.DEFAULT_TYPE):
            chat_id = context.job.data.get('chat_id')
            
            # Check marktsituatie
            volatility = get_gold_volatility()
            
            # Weekend-boost: zo/ma scant elke 10 min
            import datetime as dt
            weekday = dt.datetime.now().weekday()  # 0=ma, 6=zo
            is_weekend_boost = weekday in (0, 6)  # Zondag of Maandag
            
            if volatility <= -2.0:
                print(f"🚨 [CRISIS MODE] Goud is {volatility}% gedaald! Radar extra alert (5 min cyclus).")
                interval = 300 # 5 minutes
            elif is_weekend_boost:
                print(f"📅 [WEEKEND BOOST] Zondag/Maandag: scan elke 10 minuten.")
                interval = 600 # 10 minutes
            else:
                interval = 900 # 15 minutes
                
            # Draai radar
            await run_marktplaats_radar(context)
            
            # Plan de volgende run in
            context.job_queue.run_once(
                dynamic_radar_job,
                when=interval,
                data={'chat_id': chat_id}
            )

        # Start de radar-loop
        application.job_queue.run_once(
            dynamic_radar_job,
            when=10, # Start 10 sec na launch
            data={'chat_id': admin_chat_id}
        )
        
        # --- Flash Dip Alert (elke 15 minuten) ---
        async def flash_dip_job(context: ContextTypes.DEFAULT_TYPE):
            chat_id = context.job.data.get('chat_id')
            now = datetime.datetime.now().timestamp()
            
            metals = ["gold", "silver"]
            for m in metals:
                # 12 uur cooldown per metaal (43200 sec)
                if now - last_flash_dip_alert.get(m, 0) < 43200:
                    continue
                    
                dip_data = check_flash_dip(metal=m, drop_threshold=2.0, rsi_threshold=35)
                if dip_data and dip_data.get("is_dip"):
                    # Trigger alert!
                    drop_pct = dip_data["drop_pct"]
                    rsi = dip_data["rsi"]
                    curr = dip_data["current_price"]
                    peak = dip_data["peak_price"]
                    nl_name = "Goud" if m == "gold" else "Zilver"
                    
                    # Strategie 2 + 3: Haal CME data op voor aanvullend macro-advies
                    cme_msg_addon = ""
                    try:
                        from cme_scraper import CMEScraper
                        _cme = CMEScraper()
                        cme_data = await _cme.fetch_warehouse_stocks(m)
                        if cme_data:
                            # Strategie 2: Divergentie score
                            etf_oz = _cme.get_etf_holdings_oz(m)
                            div_score, div_label = _cme.compute_divergence_score(cme_data, etf_oz)
                            # Strategie 3: Dip-koop signaal
                            is_buy, buy_msg = _cme.compute_dip_buy_signal(cme_data, drop_pct)
                            cme_msg_addon = f"\n\n{buy_msg}\n\n📊 *CME Macro Score:* {div_score}/100\n{div_label}"
                    except Exception as _e:
                        print(f"⚠️ [CME] Fout bij dip-signaal check: {_e}")
                    
                    # Haal snelle dealer premiums op voor context
                    dealer_data = await fetch_dealer_premiums({"metaal": "goud" if m == "gold" else "zilver", "type": "munt", "gewicht_oz": 1.0})
                    product_key = "Krugerrand Goud (1 Oz)" if m == "gold" else "Maple Leaf Zilver (1 Oz)"
                    
                    best_dealer = "Onbekend"
                    best_prem = 0.0
                    
                    if product_key in dealer_data and len(dealer_data[product_key]) > 0:
                        offers = dealer_data[product_key]
                        live_offers = [o for o in offers if o["method"] == "LIVE_SCRAPE"]
                        # Probeer eerst LIVE aanbiedingen, zo niet neem ALGO
                        offer_list = live_offers if live_offers else offers
                        if offer_list:
                            best_offer = min(offer_list, key=lambda x: x["ask_price"])
                            best_dealer = best_offer["dealer_name"]
                            best_prem = ((best_offer["ask_price"] - curr) / curr) * 100
                            
                    msg = (
                        f"🔴 *FLASH DIP ALERT: {nl_name}*\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"📉 Spotprijs is in 24u met {drop_pct}% gedaald.\n"
                        f"💶 Huidige spot: €{curr:.2f} (Piek was €{peak:.2f})\n"
                        f"📊 Indicator (RSI): {rsi:.1f} (Extreem Oversold)\n\n"
                        f"💡 *Marktkans:*\n"
                        f"*{best_dealer}* verkoopt 1 Oz munt momenteel met een premium van +{best_prem:.1f}%."
                        f"{cme_msg_addon}"
                    )
                    
                    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
                    
                    # Update cooldown
                    last_flash_dip_alert[m] = now
                    
                    # SMART TRIGGER: Flush Cache & Forceer Update
                    print(f"🚨 [Smart Trigger] Flash Dip on {m}. Triggering Price Cache Refresh!")
                    if context.job_queue:
                        context.job_queue.run_once(periodic_price_cache_job, when=1)
                    
            # Plan volgende loop over 15 minuten
            context.job_queue.run_once(flash_dip_job, when=900, data={'chat_id': chat_id})
            
        # Start Flash Dip Job na 1 minuut (zodat andere tasks eerst initialiseren)
        application.job_queue.run_once(
            flash_dip_job, 
            when=60,
            data={'chat_id': admin_chat_id}
        )
        
                # --- Periodic Price Cache Job (08:30, 12:00, 14:30, 18:00) ---
        async def periodic_price_cache_job(context: ContextTypes.DEFAULT_TYPE):
            print("🕒 [Cron] SQLite Price Cache Refresh gestart...")
            common_items = [
                {"metaal": "goud", "type": "munt", "gewicht_oz": 1.0},
                {"metaal": "zilver", "type": "munt", "gewicht_oz": 1.0},
                {"metaal": "zilver", "type": "baar", "gewicht_oz": 32.15}
            ]
            for item in common_items:
                # Force refresh via SQLite door max_age=0 mee te geven
                await get_cached_dealer_premiums(item, max_age_seconds=0)
                await asyncio.sleep(2)
        
        # Schema voor gerichte database updates m.b.t. dealer prijzen:
        cache_times = [
            datetime.time(hour=8, minute=30, tzinfo=amsterdam_tz),
            datetime.time(hour=12, minute=0, tzinfo=amsterdam_tz),
            datetime.time(hour=14, minute=30, tzinfo=amsterdam_tz),
            datetime.time(hour=18, minute=0, tzinfo=amsterdam_tz)
        ]
        
        for t in cache_times:
            application.job_queue.run_daily(
                periodic_price_cache_job,
                time=t
            )
        
        # --- Dagelijkse Ochtend-Digest (08:00) ---
        async def daily_digest_job(context: ContextTypes.DEFAULT_TYPE):
            chat_id = context.job.data.get('chat_id')
            s = get_today_stats()
            q = get_quota_status()
            spot_prices = get_live_spot_prices()
            gold_price = spot_prices.get('gold_eur_oz_physical', 0)
            silver_price = spot_prices.get('silver_eur_oz_physical', 0)
            
            msg = (
                f"\u2600\ufe0f *Goedemorgen! Hier is je Radar Rapport:*\n\n"
                f"\ud83d\udcca *Markt:* Goud \u20ac{gold_price:.0f} | Zilver \u20ac{silver_price:.2f}\n"
                f"\ud83d\udd0d *Gescand:* {s['scanned']} advertenties\n"
                f"\ud83d\udeab *Gefilterd:* {s['filtered']} (spam/te duur)\n"
                f"\ud83e\udd16 *AI geanalyseerd:* {s['ai_scanned']}\n"
                f"\ud83c\udfaf *Deals gevonden:* {s['deals']}\n"
                f"\ud83d\udcb3 *API Quota:* {q['calls_today']}/{q['max_daily']} ({q['percentage_used']}%)\n\n"
                f"\u2705 Status: Alles draait soepel."
            )
            await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
        
        digest_time = datetime.time(hour=8, minute=0, tzinfo=amsterdam_tz)
        application.job_queue.run_daily(
            daily_digest_job,
            time=digest_time,
            data={'chat_id': admin_chat_id}
        )
        
        # --- Dagelijkse Premium Kalibratie (06:00) ---
        async def premium_calibration_job(context: ContextTypes.DEFAULT_TYPE):
            print("🕒 [Cron] Ochtend Kalibratie Run gestart...")
            spot_prices = get_live_spot_prices()
            if spot_prices:
                await calibrate_dealer_premiums(spot_prices)
                
        calib_time = datetime.time(hour=6, minute=0, tzinfo=amsterdam_tz)
        application.job_queue.run_daily(
            premium_calibration_job,
            time=calib_time
        )
        
        # --- Dagelijkse CME Supply Squeeze Monitor (18:15) ---
        async def cme_monitor_job(context: ContextTypes.DEFAULT_TYPE):
            chat_id = context.job.data.get('chat_id')
            try:
                print("🕒 [Cron] CME Group: Contoleren op Short Squeeze metrics...")
                scraper = CMEScraper()
                ag_data = await scraper.fetch_warehouse_stocks("silver")
                
                if ag_data and ag_data["total"] > 0:
                    # Squeeze Trigger: Als Registered Zilver onder 10% van Total (Eligible + Registered) duikt
                    reg_ratio = (ag_data["registered"] / ag_data["total"]) * 100
                    
                    if reg_ratio < 10.0:
                        msg = (
                            f"\u26a0\ufe0f *Markt Krapte Waarschuwing (ZILVER)*\n"
                            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
                            f"\ud83d\udcc9 *COMEX Fysieke Squeeze Gevaar!*\n"
                            f"Fysieke leveringsdruk op CME waarschuwt voor schaarste.\n\n"
                            f"\ud83d\uddc4\ufe0f *Registered Stock:* {ag_data['registered']:,.0f} Oz\n"
                            f"\ud83d\udcca *Registered Ratio:* {reg_ratio:.1f}% (Kritiek, <10%)\n\n"
                            f"\ud83d\udca1 *MACRO ADVIES:*\n"
                            f"Extreem Bullish. Vermijd short-posities, anticipeer op stijgende premiums. Houd fysiek zilver goed vast."
                        )
                        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
                        print("🚨 [CME] Squeeze Waarschuwing verzonden!")
                    else:
                        print(f"✅ [CME] Zilver ratio veilig op {reg_ratio:.1f}%")
                        
            except Exception as e:
                print(f"❌ [Cron] Fout in CME Monitor Job: {e}")
                
        cme_time = datetime.time(hour=18, minute=15, tzinfo=amsterdam_tz)
        application.job_queue.run_daily(
            cme_monitor_job,
            time=cme_time,
            data={'chat_id': admin_chat_id}
        )
        
        # --- Wekelijks Weekoverzicht (Zondag 20:00) ---
        async def weekly_report_job(context: ContextTypes.DEFAULT_TYPE):
            chat_id = context.job.data.get('chat_id')
            s = get_week_stats()
            q = get_quota_status()
            
            msg = (
                f"\ud83d\udcca *Weekoverzicht*\n\n"
                f"\ud83d\udd0d Gescand: *{s['scanned']}* ads\n"
                f"\ud83d\udeab Gefilterd: *{s['filtered']}*\n"
                f"\ud83e\udd16 AI: *{s['ai_scanned']}*\n"
                f"\ud83c\udfaf Deals: *{s['deals']}*\n\n"
                f"\ud83d\udcb3 API vandaag: {q['calls_today']}/{q['max_daily']}\n"
                f"Tot volgende week! \ud83d\udcaa"
            )
            await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
        
        weekly_time = datetime.time(hour=20, minute=0, tzinfo=amsterdam_tz)
        application.job_queue.run_daily(
            weekly_report_job,
            time=weekly_time,
            days=(6,),  # Alleen op zondag
            data={'chat_id': admin_chat_id}
        )
        
        # --- Zes-uurlijkse GSR Monitor ---
        async def gsr_monitor_job(context: ContextTypes.DEFAULT_TYPE):
            chat_id = context.job.data.get('chat_id')
            spot_prices = get_live_spot_prices()
            spot_gold = spot_prices.get('gold_eur_oz_physical', 0)
            spot_silver = spot_prices.get('silver_eur_oz_physical', 0)
            if not spot_gold or not spot_silver: return
            
            gsr = spot_gold / spot_silver
            
            # Check of we in extreme over/onderwaardering zitten
            if gsr >= 80:
                msg = f"🚨 *MACRO ALERT: Zilver is zwaar ondergewaardeerd*\n\nDe Goud/Zilver ratio staat momenteel op *{gsr:.1f}:1* (grens: 80).\n\nHistorisch gezien is zilver nu erg goedkoop t.o.v. goud. Advies: *Focus de radar op Zilver.*"
                await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
            elif gsr < 60:
                msg = f"🚨 *MACRO ALERT: Goud is relatief goedkoop*\n\nDe Goud/Zilver ratio staat momenteel op *{gsr:.1f}:1* (grens: 60).\n\nHistorisch gezien piekt zilver. Advies: *Focus op Goud of overweeg de zilver/goud swap.*"
                await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")

        # Start GSR check job elke 6 uur
        application.job_queue.run_repeating(
            gsr_monitor_job,
            interval=6 * 3600,
            first=300, # Start 5 minuten na launch
            data={'chat_id': admin_chat_id}
        )
    
    application.run_polling()

if __name__ == '__main__':
    main()
