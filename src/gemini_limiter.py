"""
Gemini API Rate Limiter & Quota Tracker
========================================
Centraal beheerpunt voor alle Gemini API calls.

Gratis Tier Limieten (Gemini 2.0 Flash):
- 15 RPM (requests per minuut)
- 1.500 RPD (requests per dag)
- 1M TPM  (tokens per minuut)

Dit module voorkomt dat de bot crasht of vastloopt door:
1. Exponential backoff bij 429 Resource Exhausted
2. Dagelijks quota bijhouden (voorkom verspilling)
3. Globale cooldown tussen API calls (min. 4 seconden)
"""

import time
import threading
import logging
from datetime import datetime, date

logger = logging.getLogger(__name__)

# ============================================================
# Configuratie
# ============================================================
MAX_RPM = 14                  # Net onder de 15 RPM limiet
MIN_DELAY_SECONDS = 60 / MAX_RPM  # ~4.3 seconden tussen calls
MAX_RPD = 1400                # Net onder de 1500 RPD limiet  
MAX_RETRIES = 3               # Maximaal 3 pogingen bij 429
BACKOFF_BASE = 10             # Start met 10 seconden wachten

# ============================================================
# State (Thread-Safe)
# ============================================================
_lock = threading.Lock()
_last_call_time = 0.0
_daily_count = 0
_daily_date = date.today()


def _reset_daily_if_needed():
    """Reset de dagelijkse teller als het een nieuwe dag is."""
    global _daily_count, _daily_date
    today = date.today()
    if today != _daily_date:
        logger.info(f"📊 [Quota] Nieuw dag-reset. Gisteren: {_daily_count} calls verbruikt.")
        _daily_count = 0
        _daily_date = today


def get_quota_status():
    """Retourneert het huidige quota-verbruik als dict."""
    with _lock:
        _reset_daily_if_needed()
        return {
            "calls_today": _daily_count,
            "max_daily": MAX_RPD,
            "remaining": MAX_RPD - _daily_count,
            "percentage_used": round((_daily_count / MAX_RPD) * 100, 1)
        }


def rate_limited_call(api_func, *args, **kwargs):
    """
    Wrapper voor elke Gemini API call.
    
    - Wacht automatisch als we te snel gaan (RPM limiet)
    - Retries met exponential backoff bij 429
    - Stopt als dagelijks quota bereikt is
    
    Gebruik:
        result = rate_limited_call(client.models.generate_content, model=..., contents=...)
    """
    global _last_call_time, _daily_count
    
    with _lock:
        _reset_daily_if_needed()
        
        # Check dagelijks quota
        if _daily_count >= MAX_RPD:
            logger.warning(f"🚨 [Quota] Dagelijks limiet bereikt ({MAX_RPD} calls). Geen API calls meer tot morgen.")
            raise QuotaExhaustedError(f"Dagelijks Gemini API limiet bereikt ({_daily_count}/{MAX_RPD})")
        
        # Throttle: wacht tot minimale interval verstreken is
        now = time.time()
        elapsed = now - _last_call_time
        if elapsed < MIN_DELAY_SECONDS:
            wait = MIN_DELAY_SECONDS - elapsed
            logger.debug(f"⏱️ [Rate] Wacht {wait:.1f}s voor RPM throttle...")
            time.sleep(wait)
        
        _last_call_time = time.time()
        _daily_count += 1
    
    # Exponential backoff retry loop
    for attempt in range(MAX_RETRIES):
        try:
            result = api_func(*args, **kwargs)
            return result
            
        except Exception as e:
            error_str = str(e).lower()
            
            # 429 Resource Exhausted - backoff en retry
            if "429" in str(e) or ("resource" in error_str and "exhausted" in error_str):
                wait_time = BACKOFF_BASE * (2 ** attempt)  # 10s, 20s, 40s
                logger.warning(f"⏳ [Rate] 429 Resource Exhausted. Poging {attempt+1}/{MAX_RETRIES}. Wacht {wait_time}s...")
                time.sleep(wait_time)
                continue
            
            # 503 Service Unavailable - kort wachten
            if "503" in str(e) or "unavailable" in error_str:
                wait_time = 5 * (attempt + 1)
                logger.warning(f"⏳ [Rate] 503 Service Unavailable. Poging {attempt+1}/{MAX_RETRIES}. Wacht {wait_time}s...")
                time.sleep(wait_time)
                continue
            
            # Andere fouten: niet herhalen
            raise
    
    # Alle retries gefaald
    raise Exception(f"Gemini API call gefaald na {MAX_RETRIES} pogingen (rate limited).")


class QuotaExhaustedError(Exception):
    """Raised wanneer het dagelijks Gemini API quota is bereikt."""
    pass
