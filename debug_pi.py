import yfinance as yf
import requests
import datetime
import os

def check_diagnostics():
    print("--- 🕵️ GoudBot Pi Diagnostics ---")
    
    # 1. Check System Time
    now = datetime.datetime.now()
    print(f"System Time: {now}")
    
    # 2. Check Internet Connectivity
    try:
        resp = requests.get("https://www.google.com", timeout=5)
        print(f"Internet: OK (Status {resp.status_code})")
    except Exception as e:
        print(f"Internet: FAILED ({e})")
        
    # 3. Check yfinance (The main problem)
    print("\nTesting Yahoo Finance (GC=F) with Session + User-Agent...")
    try:
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
        })
        
        ticker = yf.Ticker("GC=F", session=session)
        hist = ticker.history(period="1d")
        if not hist.empty:
            price = hist['Close'].iloc[-1]
            print(f"yfinance: OK (Price: {price})")
        else:
            print("yfinance: FAILED (Empty DataFrame - try running 'pip install --upgrade yfinance')")
    except Exception as e:
        print(f"yfinance: ERROR ({e})")

    # 4. Check Ollama Connectivity
    print("\nTesting Ollama Connectivity (Port 11434)...")
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=5)
        if resp.status_code == 200:
            print(f"Ollama: OK (Models: {resp.json().get('models', [])})")
        else:
            print(f"Ollama: FAILED (Status {resp.status_code})")
    except Exception as e:
        print(f"Ollama: FAILED (Is Ollama running? Error: {e})")

if __name__ == "__main__":
    check_diagnostics()
