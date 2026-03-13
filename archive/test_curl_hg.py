from curl_cffi import requests
import time

def test_hollandgold():
    print("Testing Holland Gold with curl_cffi...")
    try:
        # Using chrome110 as it should be available in older curl_cffi
        session = requests.Session(impersonate="chrome110")
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.google.nl/",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        
        url = "https://www.hollandgold.nl/koersen"
        response = session.get(url, headers=headers)
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            print("Successfully fetched the page!")
            print(f"Content Length: {len(response.text)}")
            if "Krugerrand" in response.text or "goud" in response.text.lower():
                print("Found expected keywords in HTML.")
        else:
            print(f"Failed. Snippet: {response.text[:500]}")
            
    except Exception as e:
        print(f"Error: {e}")

test_hollandgold()
