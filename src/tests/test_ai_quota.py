import sys
import os
from PIL import Image

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))
from expert_agent import pre_scan_image

test_img = "dummy_test_image.jpg"
if not os.path.exists(test_img):
    img = Image.new('RGB', (100, 100), color = 'red')
    img.save(test_img)

ad_context = "Advertentie Titel: Nederland. Wilhelmina. 10 Gulden 1933\nBeschrijving: Prachtig gouden tientje."

print("Testing Gemini Quote with Wilhelmina ad...")
res = pre_scan_image([test_img], text_context=ad_context)
print(f"Result: {res}")
