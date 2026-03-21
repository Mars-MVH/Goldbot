import os
import json
import base64
import requests
import logging
from io import BytesIO
from PIL import Image
from gemini_limiter import rate_limited_call, QuotaExhaustedError

logger = logging.getLogger(__name__)

class AIProvider:
    GEMINI = "gemini"
    OLLAMA = "ollama"

def router_generate_content(prompt, images=None, system_instruction=None, model_override=None, require_json=False):
    """
    Universele router voor AI-content generatie.
    
    Args:
        prompt (str): De hoofdtekst of vraag voor de AI.
        images (list[str], optional): Lijst van absolute paden naar afbeeldingen.
        system_instruction (str, optional): Instructies voor de system prompt.
        model_override (str, optional): Specifiek model (bijv. 'moondream' voor vision).
        require_json (bool, optional): Forceer de output naar dict format.
        
    Returns:
        dict | str: De geparseerde JSON output of de pure string.
    """
    provider = os.environ.get("AI_PROVIDER", AIProvider.GEMINI).lower()
    
    # 1. Gemini Cloud Path
    if provider == AIProvider.GEMINI:
        try:
            return _call_gemini(prompt, images, system_instruction, require_json)
        except QuotaExhaustedError:
            logger.warning("🚨 [Router] Gemini Quota Exhausted. Checking for Local Fallback...")
            if os.environ.get("AUTO_FALLBACK_TO_OLLAMA", "false").lower() == "true":
                return _call_ollama(prompt, images, system_instruction, model_override, require_json)
            raise
    
    # 2. Ollama Local Path
    elif provider == AIProvider.OLLAMA:
        return _call_ollama(prompt, images, system_instruction, model_override, require_json)
    
    else:
        raise ValueError(f"Onbekende AI_PROVIDER: {provider}")

def _call_gemini(prompt, image_paths, system_instruction, require_json=False):
    """Aanroep naar Google Gemini API."""
    from google import genai
    from google.genai import types
    
    api_key = os.environ.get("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)
    
    # Combineer system prompt en user prompt
    full_prompt = prompt
    if system_instruction:
        full_prompt = f"{system_instruction}\n\nUSER REQUEST:\n{prompt}"
        
    contents = [full_prompt]
    if image_paths:
        for img_path in image_paths:
            contents.append(Image.open(img_path))
            
    # Gebruik de bestaande rate limiter
    kwargs = {
        "model": 'gemini-2.0-flash', # Of 1.5-flash
        "contents": contents
    }
    
    if require_json:
        kwargs["config"] = types.GenerateContentConfig(response_mime_type="application/json")
        
    result = rate_limited_call(client.models.generate_content, **kwargs)
    
    if require_json:
        try:
            return json.loads(result.text)
        except Exception as e:
            return {"fout": "Parsen van JSON mislukt", "raw": result.text}
            
    return result.text

def _call_ollama(prompt, image_paths, system_instruction, model_override, require_json=False):
    """Aanroep naar een lokale Ollama instance."""
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    
    # Bepaal model
    # Tekst focus: llama3:8b (of gemma2)
    # Vision focus: moondream (of llava)
    if image_paths:
        model = model_override or os.environ.get("OLLAMA_VISION_MODEL", "qwen2.5vl:3b")
    else:
        model = model_override or os.environ.get("OLLAMA_TEXT_MODEL", "llama3:8b")
        
    logger.info(f"🤖 [Router] Calling Ollama Local ({model})...")
    
    url = f"{host}/api/generate"
    
    payload = {
        "model": model,
        "prompt": f"{system_instruction}\n\n{prompt}" if system_instruction else prompt,
        "stream": False
    }
    if require_json:
        payload["format"] = "json"
    
    if image_paths:
        # Ollama verwacht base64 strings voor afbeeldingen
        encoded_images = []
        for img_path in image_paths:
            try:
                # Verklein resolutie zodat Ollama Vision op Pi niet vastloopt (max 800x800)
                from PIL import Image
                with Image.open(img_path) as img:
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    img.thumbnail((800, 800), Image.Resampling.LANCZOS)
                    buffered = BytesIO()
                    img.save(buffered, format="JPEG", quality=85)
                    encoded_string = base64.b64encode(buffered.getvalue()).decode('utf-8')
                    encoded_images.append(encoded_string)
            except Exception as e:
                logger.error(f"Fout bij optimaliseren foto voor Ollama: {e}")
                # Fallback naar origineel
                with open(img_path, "rb") as image_file:
                    encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                    encoded_images.append(encoded_string)
        payload["images"] = encoded_images
        
    try:
        # Paging zware modellen in RAM op een volle Pi kan lang duren. We gebruiken een dubbele poging met royale timeout.
        try:
            response = requests.post(url, json=payload, timeout=300)
            response.raise_for_status()
        except requests.exceptions.ReadTimeout:
            logger.warning("⏳ [Router] Ollama timeout na 300s. CPU is waarschijnlijk druk aan het inladen. Retry in 5s...")
            import time
            time.sleep(5)
            response = requests.post(url, json=payload, timeout=300)
            response.raise_for_status()
            
        result_json = response.json()
        
        # Ollama geeft het antwoord in het 'response' veld
        raw_text = result_json.get("response", "")
        
        if require_json:
            try:
                if not raw_text.strip(): return {}
                return json.loads(raw_text)
            except Exception as e:
                logger.error(f"❌ [Router] Ollama JSON Parse Error: {e}")
                return {"fout": "JSON parse error", "raw": raw_text}
                
        return raw_text
        
    except Exception as e:
        logger.error(f"❌ [Router] Ollama Error: {e}")
        raise
