import sys
import os
from PIL import Image

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))
from expert_agent import pre_scan_image

# Maak een fysieke lege dummy image
test_img = "dummy_test_image.jpg"
img = Image.new('RGB', (100, 100), color = 'red')
img.save(test_img)

print("--- Test 1: Gouden Tientje (10 Gulden) ---")
ad_context = "Advertentie Titel: Nederland. Wilhelmina. 10 Gulden 1933\nBeschrijving: Prachtig gouden tientje."
res1 = pre_scan_image([test_img], text_context=ad_context)

print("\n\n--- Test 2: 10 Gram Baar (De eerste screenshot fail) ---")
ad_context = "Advertentie Titel: 10 gram - Goud .999 - Umicore, Belgium\nBeschrijving: 10 gram goudbaar in verpakking."
res2 = pre_scan_image([test_img], text_context=ad_context)

print("\n--- EIND RESULTATEN ---")
print(f"Test 1 (Verwacht Oz ~0.1947): {res1}")
print(f"Test 2 (Verwacht Oz ~0.3215): {res2}")
