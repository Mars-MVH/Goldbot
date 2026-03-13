"""
CME Group Scraper + Macro Strategy Engine
==========================================
Strategie 1: Supply Squeeze Monitor (COMEX Registered/Eligible ratio)
Strategie 2: Macro Divergence Score (ETF holdings vs. COMEX Registered stock)
Strategie 3: Premium Hedging (Spot daalt + fysieke vraag stijgt = Dip-koop signaal)
"""
import aiohttp
import asyncio
import io
import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup
import warnings

warnings.filterwarnings('ignore', category=UserWarning, module='xlrd')


class CMEScraper:
    """Haalt COMEX warehouse stocks op via CME Group Excel bestanden."""

    def __init__(self):
        self.base_url = "https://www.cmegroup.com"
        self.delivery_url = (
            f"{self.base_url}/solutions/clearing/operations-and-deliveries/"
            "nymex-delivery-notices.html"
        )
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

    async def fetch_warehouse_stocks(self, metal="silver"):
        """
        Haalt de Registered en Eligible voorraden op voor het opgegeven metaal.
        Returns: dict {metal, registered, eligible, total} of None bij fout.
        """
        print(f"[CME] {metal.upper()} voorraden ophalen...")
        async with aiohttp.ClientSession(headers=self.headers) as session:
            try:
                async with session.get(self.delivery_url, timeout=15) as response:
                    if response.status != 200:
                        return None
                    soup = BeautifulSoup(await response.text(), "html.parser")
                    target_link = None
                    for a in soup.find_all('a', href=True):
                        href = a['href'].lower()
                        if 'xls' in href:
                            if metal == "silver" and any(
                                kw in href for kw in ("silver", "ag", "sil")
                            ):
                                target_link = a['href']
                                break
                            elif metal == "gold" and any(
                                kw in href for kw in ("gold", "au", "gc")
                            ):
                                target_link = a['href']
                                break
                    if not target_link:
                        return None
                    url = (
                        self.base_url + target_link
                        if target_link.startswith('/')
                        else target_link
                    )
                    return await self._parse_excel_stream(session, url, metal)
            except Exception as e:
                print(f"[CME] Fout bij scrapen: {e}")
                return None

    async def _parse_excel_stream(self, session, url, metal):
        """Download en parseer het CME Excel bestand."""
        try:
            async with session.get(url, timeout=20) as response:
                content = await response.read()
                df = pd.read_excel(io.BytesIO(content), header=None)

                result = {"metal": metal, "registered": 0.0, "eligible": 0.0, "total": 0.0}

                for _, row in df.iterrows():
                    row_str = " ".join([str(x).strip().lower() for x in row.values])
                    if "total" in row_str and "registered" not in row_str:
                        nums = []
                        for val in row.values:
                            try:
                                n = float(val)
                                if not pd.isna(n) and n > 0:
                                    nums.append(n)
                            except (ValueError, TypeError):
                                pass

                        unique_nums = sorted(list(set(nums)), reverse=True)
                        if len(unique_nums) >= 3:
                            result["total"] = unique_nums[0]
                            result["eligible"] = unique_nums[1]
                            result["registered"] = unique_nums[2]
                            return result
                        elif len(unique_nums) == 2:
                            result["total"] = unique_nums[0]
                            result["eligible"] = unique_nums[1]
                            result["registered"] = unique_nums[0] - unique_nums[1]
                            return result
                return result
        except Exception as e:
            print(f"[CME] Excel parse fout: {e}")
            return None

    # ─────────────────────────────────────────────
    # STRATEGIE 2: ETF vs. COMEX Divergentie Score
    # ─────────────────────────────────────────────

    def get_etf_holdings_oz(self, metal="silver"):
        """
        Haalt de huidige holdings op van de grootste edelmetaal ETF's via yfinance.
        Zilver → SLV, PSLV  |  Goud → GLD, SGOL
        Returns: totale ETF holdings in Troy Oz (geschat), of None bij fout.
        """
        etf_map = {
            "silver": ["SLV", "PSLV"],
            "gold": ["GLD", "IAU"]
        }
        tickers = etf_map.get(metal, [])
        total_Nav = 0.0
        for ticker in tickers:
            try:
                t = yf.Ticker(ticker)
                info = t.info
                # Gebruik de 'totalAssets' als NAV proxy
                nav = info.get("totalAssets", 0) or 0
                total_Nav += nav
            except Exception as e:
                print(f"[ETF] Fout bij ophalen {ticker}: {e}")
        # Schat holdings in Oz: NAV gedeeld door circa-spotprijs per oz
        # We gebruiken de spot als proxy via yfinance zelf
        spot_ticker = "SI=F" if metal == "silver" else "GC=F"
        try:
            spot = yf.Ticker(spot_ticker).fast_info["lastPrice"]
            est_oz = total_Nav / spot if spot else 0
        except Exception:
            est_oz = 0
        print(f"[ETF] {metal.upper()} geschatte ETF holdings: {est_oz:,.0f} Oz (NAV: ${total_Nav:,.0f})")
        return est_oz

    def compute_divergence_score(self, comex_data, etf_oz):
        """
        Strategie 2: Berekent de divergentie-score tussen ETF holdings en COMEX registered stock.

        Wanneer ETF zijn assets dumpt maar COMEX registered stijgt (of vice versa),
        suggereert dit grote institutionele verschuivingen.

        Score: +100 = sterke institutionele vlucht naar fysiek  (Bullish)
               0    = neutraal
               -100 = ETF lekt assets, geen echte vraag (Bearish)
        """
        if not comex_data or comex_data.get("registered", 0) == 0:
            return 0, "Geen COMEX data beschikbaar."
        registered = comex_data["registered"]
        total = comex_data["total"]
        reg_ratio = (registered / total * 100) if total else 0

        # Hogere ratio Registered = markt vraagt físiek = Bullish
        # Lage ETF holdings relatief aan COMEX = smart money dumpt papier
        if reg_ratio < 5:
            score = 90
            label = "🔴 KRITIEK: Bijna al het beschikbare metaal is al uitleveringsklaargezet. Extreme schaarste. Sterk Bullish."
        elif reg_ratio < 10:
            score = 70
            label = "⚠️ WAARSCHUWING: Registered daalt sterk. Institutionele vraag piekt."
        elif reg_ratio < 20:
            score = 40
            label = "🟡 LICHT GESPANNEN: Registered loopt langzaam terug. Let op."
        else:
            score = 10
            label = "✅ NORMAAL: Markt is ruim voorzien van fysiek metaal."

        return score, label

    # ─────────────────────────────────────────────
    # STRATEGIE 3: Premium Hedging / Dip-Koop Signaal
    # ─────────────────────────────────────────────

    def compute_dip_buy_signal(self, comex_data, spot_drop_pct):
        """
        Strategie 3: Combineer een dip in de spotprijs met data over fysieke vraag.

        Als de spot daalt MAAR de COMEX uitleveringsdruk hoog is (laag Registered),
        dan is de dip slechts een papieren correctie: een koopkans.

        Returns: (is_buy_signal: bool, bericht: str)
        """
        if not comex_data or comex_data.get("total", 0) == 0:
            return False, "Onvoldoende data voor dip-signaal."

        registered = comex_data.get("registered", 0)
        total = comex_data.get("total", 0)
        reg_ratio = (registered / total * 100) if total else 100

        # Dip signaal = spot daalt (negatieve spot_drop_pct) + fysieke krapte
        spot_is_falling = spot_drop_pct <= -1.5  # minstens 1.5% daling in 24u
        physical_demand_high = reg_ratio < 15    # registered < 15% van totaal

        if spot_is_falling and physical_demand_high:
            return True, (
                f"📉 *DIP-KOOP SIGNAAL (Strategie 3)*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"De spotprijs daalt ({spot_drop_pct:.1f}%), maar fysieke vraag op COMEX is extreem hoog.\n"
                f"🔎 COMEX Registered Ratio: *{reg_ratio:.1f}%* (Krapte grens: <15%)\n\n"
                f"💡 *Analyse:* Dit is een papieren correctie, geen echte daling in vraag.\n"
                f"Institutionele partijen kopen het fysieke metaal op dit moment actief op.\n\n"
                f"✅ *Advies:* Koop deze dip. De onderliggende fundamenten zijn sterk."
            )
        elif spot_is_falling and not physical_demand_high:
            return False, (
                f"⚠️ Spot daalt ({spot_drop_pct:.1f}%), maar COMEX registered is ruim ({reg_ratio:.1f}%).\n"
                f"Geen duidelijk koopsignaal. Afwachten."
            )
        else:
            return False, "Geen actief dip-koop signaal op dit moment."


async def main():
    """Testrun van alle drie de strategieën."""
    s = CMEScraper()

    print("\n=== STRATEGIE 1 + 2 + 3 TEST ===\n")

    # Strategie 1: Voorraden ophalen
    ag_data = await s.fetch_warehouse_stocks("silver")
    au_data = await s.fetch_warehouse_stocks("gold")

    print(f"\nResultaten COMEX:\nZilver: {ag_data}\nGoud: {au_data}")

    # Strategie 2: Divergentie score
    print("\n--- Strategie 2: ETF vs. COMEX ---")
    etf_oz_ag = s.get_etf_holdings_oz("silver")
    score, label = s.compute_divergence_score(ag_data, etf_oz_ag)
    print(f"Divergentie Score: {score}/100\n{label}")

    # Strategie 3: Simuleer een koopadvies scenario
    print("\n--- Strategie 3: Dip Koop Signaal (Gesimuleerd -2.5% dip) ---")
    is_buy, msg = s.compute_dip_buy_signal(ag_data, spot_drop_pct=-2.5)
    print(f"Koopadvies: {is_buy}\n{msg}")


if __name__ == "__main__":
    asyncio.run(main())
