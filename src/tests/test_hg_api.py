from playwright.sync_api import sync_playwright
import time
import json

def intercept_network():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Using a convincing user agent
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()

        # We will collect all XHR/Fetch requests
        api_calls = []

        def handle_response(response):
            # Only care about fetch/xhr or document returning json
            if response.request.resource_type in ["fetch", "xhr", "document"]:
                try:
                    url = response.url
                    # filter out obvious static assets or tracking
                    if "google" in url or "facebook" in url or "clarity" in url or "klaviyo" in url:
                        return
                        
                    if "price" in url.lower() or "graphql" in url.lower() or "api" in url.lower():
                        body = response.text()
                        api_calls.append({
                            "url": url,
                            "status": response.status,
                            "type": response.request.resource_type,
                            "body_snippet": body[:500] if body else ""
                        })
                except Exception as e:
                    pass

        page.on("response", handle_response)

        print("Navigating to Holland Gold Krugerrand page...")
        # A known product page
        target_url = "https://www.hollandgold.nl/krugerrand-1-troy-ounce-gouden-munt-div-jaartallen.html"
        
        try:
            page.goto(target_url, wait_until="networkidle", timeout=15000)
            print("Page loaded. Waiting 3 extra seconds for dynamic content...")
            time.sleep(3)
        except Exception as e:
            print(f"Navigation error: {e}")

        browser.close()

        print("\n=== INTERCEPTED API CALLS ===")
        for call in api_calls:
            print(f"URL: {call['url']}")
            print(f"Type: {call['type']} | Status: {call['status']}")
            print(f"Body: {call['body_snippet']}")
            print("-" * 50)

if __name__ == "__main__":
    intercept_network()
