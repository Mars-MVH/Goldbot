import yfinance as yf
import pandas as pd

ticker_usd = "GC=F"
days = 30

data_metal = yf.download(ticker_usd, period=f"{days}d", progress=False)
data_eur = yf.download("EURUSD=X", period=f"{days}d", progress=False)

prices_usd = data_metal['Close']
fx_rate = data_eur['Close']

print("USD Prices:")
print(prices_usd.tail())
print("FX Prices:")
print(fx_rate.tail())

# We hoeven niet te dropna op join, maar forward fillen 
combined = pd.concat([prices_usd, fx_rate], axis=1)
combined.columns = ['USD_Gold', 'EUR_USD']
combined = combined.ffill().dropna()

prices_eur = combined['USD_Gold'] / combined['EUR_USD']
print("EUR Prices:")
print(prices_eur.tail())
