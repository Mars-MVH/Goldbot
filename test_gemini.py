from src.ai_router import router_generate_content
import os
from dotenv import load_dotenv

load_dotenv()

print("AI_PROVIDER:", os.getenv("AI_PROVIDER"))
print("KEY:", os.getenv("GEMINI_API_KEY")[:5] if os.getenv("GEMINI_API_KEY") else "None")

res1 = router_generate_content("Wat is 1+1?", require_json=False)
print("TEST 1 (Text):", res1)

res2 = router_generate_content("Geef me json { 'a': 1 }", require_json=True)
print("TEST 2 (JSON):", res2)
