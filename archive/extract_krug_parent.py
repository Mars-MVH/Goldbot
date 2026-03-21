import time
from playwright.sync_api import sync_playwright

def dump():
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page()
        page.goto('https://www.hollandgold.nl/verkopen/gouden-munten.html', wait_until='networkidle')
        time.sleep(3)
        # Find element containing the text
        elements = page.locator("text='Krugerrand 1 troy ounce gouden munt - diverse jaartallen'")
        count = elements.count()
        print(f"Found {count} elements")
        if count > 0:
            # Get the parent row
            row = elements.nth(0).locator("xpath=ancestor::div[contains(@class, 'price-table__row')] | ancestor::tr | ..")
            print("--- TEXT ---")
            print(row.inner_text())
            print("--- HTML ---")
            print(row.inner_html())
        b.close()

if __name__ == "__main__":
    dump()
