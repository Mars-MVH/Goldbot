import sqlite3
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'radar_memory.db')

def init_db():
    """Initialiseert de SQLite database en maakt de benodigde tabellen aan indien ze niet bestaan."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Tabel voor gescande advertenties om herhaling in notificaties of API kosten te vermijden
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS seen_ads (
                url TEXT PRIMARY KEY,
                price_at_scan REAL,
                spot_price_at_scan REAL,
                timestamp TEXT,
                status TEXT
            )
        ''')
        
        # Portfolio Kluis: Handmatig bijgehouden bezittingen
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS portfolio (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product TEXT NOT NULL,
                weight_oz REAL DEFAULT 1.0,
                metal TEXT DEFAULT 'goud',
                purchase_price REAL NOT NULL,
                purchase_date TEXT NOT NULL,
                amount INTEGER DEFAULT 1
            )
        ''')
        
        # Migratie script voor bestaande databases
        try:
            cursor.execute("ALTER TABLE portfolio ADD COLUMN amount INTEGER DEFAULT 1")
        except sqlite3.OperationalError:
            pass # Kolom bestaat al
        
        # Radar Stats: Dagelijkse scan-statistieken voor digest/weekoverzicht
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS radar_stats (
                date TEXT NOT NULL,
                ads_scanned INTEGER DEFAULT 0,
                ads_filtered INTEGER DEFAULT 0,
                ads_ai_scanned INTEGER DEFAULT 0,
                deals_found INTEGER DEFAULT 0,
                PRIMARY KEY (date)
            )
        ''')
        
        # Price Cache: Opgeslagen json dicts voor dealer prijzen om server/API laadtijd te minimaliseren
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS price_cache (
                cache_key TEXT PRIMARY KEY,
                dealer_data_json TEXT NOT NULL,
                timestamp REAL NOT NULL
            )
        ''')
        
        conn.commit()
        logger.info(f"✅ SQLite Database succesvol geïnitialiseerd op: {DB_PATH}")
        return conn
    except Exception as e:
        logger.error(f"❌ Fout tijdens initialiseren van SQLite Database: {e}")
        return None
    finally:
        if 'conn' in locals() and conn:
            conn.close()

def ad_exists(url, current_price):
    """
    Controleert of een advertentie al gezien is.
    Retourneert True als de ad bestaat EN de prijs gelijk is gebleven of is gestegen (negeren).
    Retourneert False als het een nieuwe ad is OF de prijs substantieel (bijv >5%) is verlaagd (wel re-scannen).
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('SELECT price_at_scan FROM seen_ads WHERE url = ?', (url,))
        result = cursor.fetchone()
        
        if result:
            old_price = result[0]
            # Als de advertentie al in DB staat, bekijk dan of er een sterke prijsdaling is (-5%)
            if old_price and current_price > 0 and current_price <= (old_price * 0.95):
                logger.info(f"📉 Prijswaarschuwing: Bekende ad '{url}' in prijs gedaald van €{old_price} naar €{current_price}!")
                return False # Ad exists, but price dropped, so return False to allow re-scan
            
            # Ad bestaat en prijs is niet gedaald, negeren.
            return True
            
        return False # Volledig nieuwe URL
        
    except Exception as e:
        logger.error(f"Fout in ad_exists check: {e}")
        return False
    finally:
        if 'conn' in locals() and conn:
            conn.close()

def save_ad(url, price_at_scan, spot_price_at_scan, status="scanned"):
    """Slaat een geanalyseerde en/of genotificeerde ad op in het permanente geheugen."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        timestamp = datetime.now().isoformat()
        
        # Gebruik REPLACE om evt een ge-update prijs te overschrijven
        cursor.execute('''
            INSERT OR REPLACE INTO seen_ads (url, price_at_scan, spot_price_at_scan, timestamp, status)
            VALUES (?, ?, ?, ?, ?)
        ''', (url, price_at_scan, spot_price_at_scan, timestamp, status))
        
        conn.commit()
    except Exception as e:
        logger.error(f"Fout tijdens opslaan ad '{url}': {e}")
    finally:
        if 'conn' in locals() and conn:
            conn.close()

# ============================================================
# Portfolio Kluis
# ============================================================
def add_portfolio_item(product, weight_oz, metal, purchase_price, amount=1):
    """Voegt een item toe aan de portfolio kluis."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        purchase_date = datetime.now().strftime("%Y-%m-%d")
        cursor.execute('''
            INSERT INTO portfolio (product, weight_oz, metal, purchase_price, purchase_date, amount)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (product, weight_oz, metal, purchase_price, purchase_date, amount))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Fout bij toevoegen portfolio item: {e}")
        return False
    finally:
        if 'conn' in locals() and conn:
            conn.close()

def get_portfolio():
    """Haalt alle portfolio items op."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT id, product, weight_oz, metal, purchase_price, purchase_date, amount FROM portfolio ORDER BY purchase_date DESC')
        return cursor.fetchall()
    except Exception as e:
        logger.error(f"Fout bij ophalen portfolio: {e}")
        return []
    finally:
        if 'conn' in locals() and conn:
            conn.close()

def remove_portfolio_item(item_id):
    """Verwijdert een item uit de portfolio kluis."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM portfolio WHERE id = ?', (item_id,))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Fout bij verwijderen portfolio item: {e}")
        return False
    finally:
        if 'conn' in locals() and conn:
            conn.close()

# ============================================================
# Radar Stats
# ============================================================
def log_radar_stats(scanned=0, filtered=0, ai_scanned=0, deals=0):
    """Logt radar statistieken voor de huidige dag (cumulatief)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        
        cursor.execute('''
            INSERT INTO radar_stats (date, ads_scanned, ads_filtered, ads_ai_scanned, deals_found)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                ads_scanned = ads_scanned + ?,
                ads_filtered = ads_filtered + ?,
                ads_ai_scanned = ads_ai_scanned + ?,
                deals_found = deals_found + ?
        ''', (today, scanned, filtered, ai_scanned, deals,
              scanned, filtered, ai_scanned, deals))
        conn.commit()
    except Exception as e:
        logger.error(f"Fout bij loggen radar stats: {e}")
    finally:
        if 'conn' in locals() and conn:
            conn.close()

def get_today_stats():
    """Haalt de radar statistieken van vandaag op."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        cursor.execute('SELECT ads_scanned, ads_filtered, ads_ai_scanned, deals_found FROM radar_stats WHERE date = ?', (today,))
        row = cursor.fetchone()
        if row:
            return {"scanned": row[0], "filtered": row[1], "ai_scanned": row[2], "deals": row[3]}
        return {"scanned": 0, "filtered": 0, "ai_scanned": 0, "deals": 0}
    except Exception as e:
        logger.error(f"Fout bij ophalen dag-stats: {e}")
        return {"scanned": 0, "filtered": 0, "ai_scanned": 0, "deals": 0}
    finally:
        if 'conn' in locals() and conn:
            conn.close()

def get_week_stats():
    """Haalt de radar statistieken van de afgelopen 7 dagen op (geaggregeerd)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT SUM(ads_scanned), SUM(ads_filtered), SUM(ads_ai_scanned), SUM(deals_found)
            FROM radar_stats
            WHERE date >= date('now', '-7 days')
        ''')
        row = cursor.fetchone()
        if row and row[0] is not None:
            return {"scanned": row[0], "filtered": row[1], "ai_scanned": row[2], "deals": row[3]}
        return {"scanned": 0, "filtered": 0, "ai_scanned": 0, "deals": 0}
    except Exception as e:
        logger.error(f"Fout bij ophalen week-stats: {e}")
        return {"scanned": 0, "filtered": 0, "ai_scanned": 0, "deals": 0}
    finally:
        if 'conn' in locals() and conn:
            conn.close()

# ============================================================
# Price Cache Manager
# ============================================================
def get_price_cache(cache_key):
    """Haalt dealer data (als text string) en tijdstempel uit de cache op."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT dealer_data_json, timestamp FROM price_cache WHERE cache_key = ?', (cache_key,))
        result = cursor.fetchone()
        if result:
            return result[0], result[1]
        return None, None
    except Exception as e:
        logger.error(f"Fout bij ophalen price_cache voor {cache_key}: {e}")
        return None, None
    finally:
        if 'conn' in locals() and conn:
            conn.close()

def set_price_cache(cache_key, dealer_data_json, timestamp):
    """Bewaart (of overschrijft) dealer data JSON en het tijdstempel in de cache."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO price_cache (cache_key, dealer_data_json, timestamp)
            VALUES (?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                dealer_data_json = excluded.dealer_data_json,
                timestamp = excluded.timestamp
        ''', (cache_key, dealer_data_json, timestamp))
        conn.commit()
    except Exception as e:
        logger.error(f"Fout bij wegschrijven price_cache voor {cache_key}: {e}")
    finally:
        if 'conn' in locals() and conn:
            conn.close()

# Initialiseer tabellen wanneer database.py voor het eerst geïmporteerd wordt
init_db()
