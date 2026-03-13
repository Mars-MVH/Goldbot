import os
import yfinance as yf
import matplotlib.pyplot as plt
import datetime

def generate_price_chart(days=30, metal="Gold"):
    """
    Haalt de Yahoo Finance papier-spot (historisch) op en maakt een grafiek (PNG).
    Geeft het lokale pad terug naar de opgeslagen grafiek, of None bij een error.
    """
    ticker_usd = "GC=F" if metal == "Gold" else "SI=F"
    title_nm = "Goud" if metal == "Gold" else "Zilver"
    
    try:
        # Haal metaal in USD op en de actuele EUR/USD wisselkoers
        data_metal = yf.download(ticker_usd, period=f"{days}d", progress=False)
        data_eur = yf.download("EURUSD=X", period=f"{days}d", progress=False)
        
        if data_metal.empty or data_eur.empty:
            return None
            
        # Maak de EUR prijs door USD te delen door EUR/USD koers
        # FillNa om weekendgaten van futures vs forex te dichten
        prices_usd = data_metal['Close']
        fx_rate = data_eur['Close']
        
        import pandas as pd
        combined = pd.concat([prices_usd, fx_rate], axis=1)
        # Forceer platte kolomnamen, omdat yfinance soms MultiIndex retourneert
        combined.columns = ['USD_Gold', 'EUR_USD']
            
        combined = combined.ffill().dropna()
        prices_eur = combined['USD_Gold'] / combined['EUR_USD']
        
        if prices_eur.empty:
            return None
            
        prices = prices_eur.squeeze()
        
        # Setup the plot
        plt.figure(figsize=(10, 5))
        plt.plot(prices.index, prices, label=f'{title_nm} Prijs (€/Oz)', color='#FFD700' if metal == "Gold" else '#C0C0C0', linewidth=2.5)
        
        # Styling
        plt.title(f"{title_nm} Trend - Laatste {days} Dagen", fontsize=14, fontweight='bold', color='#333333')
        plt.ylabel("Euro (€)", fontsize=12)
        plt.xlabel("Datum", fontsize=12)
        plt.grid(color='gray', linestyle='--', linewidth=0.5, alpha=0.5)
        
        # Zwarte achtergrond/Darkmode is luxer
        ax = plt.gca()
        ax.set_facecolor('#1e1e1e')
        plt.gcf().patch.set_facecolor('#f4f4f4')
        
        plt.legend(loc='upper left')
        plt.tight_layout()
        
        # Bestandsnaam
        os.makedirs("temp_cart", exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = f"temp_cart/chart_{metal.lower()}_{timestamp}.png"
        
        plt.savefig(filepath, dpi=150)
        plt.close()
        
        return filepath
        
    except Exception as e:
        print(f"Error generating chart for {metal}: {e}")
        return None
