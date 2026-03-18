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

def router_generate_content(prompt, images=None, system_instruction=None, model_override=None):
    """
    Universele router voor AI-content generatie.
    
    Args:
        prompt (str): De hoofdtekst of vraag voor de AI.
        images (list[str], optional): Lijst van absolute paden naar afbeeldingen.
        system_instruction (str, optional): Instructies voor de system prompt.
        model_override (str, optional): Specifiek model (bijv. 'moondream' voor vision).
        
    Returns:
        dict: De geparseerde JSON output van het model.
    """
    provider = os.environ.get("AI_PROVIDER", AIProvider.GEMINI).lower()
    
    # 1. Gemini Cloud Path
    if provider == AIProvider.GEMINI:
        try:
            return _call_gemini(prompt, images, system_instruction)
        except QuotaExhaustedError:
            logger.warning("🚨 [Router] Gemini Quota Exhausted. Checking for Local Fallback...")
            # Optioneel: automatische fallback naar Ollama als poort open staat
            if os.environ.get("AUTO_FALLBACK_TO_OLLAMA", "false").lower() == "true":
                return _call_ollama(prompt, images, system_instruction, model_override)
            raise
    
    # 2. Ollama Local Path
    elif provider == AIProvider.OLLAMA:
        return _call_ollama(prompt, images, system_instruction, model_override)
    
    else:
        raise ValueError(f"Onbekende AI_PROVIDER: {provider}")

def _call_gemini(prompt, image_paths, system_instruction):
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
    result = rate_limited_call(
        client.models.generate_content,
        model='gemini-2.0-flash', # Of 1.5-flash
        contents=contents,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
        )
    )
    
    return json.loads(result.text)

def _call_ollama(prompt, image_paths, system_instruction, model_override):
    """Aanroep naar een lokale Ollama instance."""
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    
    # Bepaal model
    # Tekst focus: llama3:8b (of gemma2)
    # Vision focus: moondream (of llava)
    if image_paths:
        model = model_override or os.environ.get("OLLAMA_VISION_MODEL", "qwen2.5-vl:3b")
    else:
        model = model_override or os.environ.get("OLLAMA_TEXT_MODEL", "llama3:8b")
        
    logger.info(f"🤖 [Router] Calling Ollama Local ({model})...")
    
    url = f"{host}/api/generate"
    
    payload = {
        "model": model,
        "prompt": f"{system_instruction}\n\n{prompt}" if system_instruction else prompt,
        "stream": False,
        "format": "json"
    }
    
    if image_paths:
        # Ollama verwacht base64 strings voor afbeeldingen
        encoded_images = []
        for img_path in image_paths:
            with open(img_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                encoded_images.append(encoded_string)
        payload["images"] = encoded_images
        
    try:
        response = requests.post(url, json=payload, timeout=180)
        response.raise_for_status()
        result_json = response.json()
        
        # Ollama geeft het antwoord in het 'response' veld
        raw_text = result_json.get("response", "{}")
        return json.loads(raw_text)
        
    except Exception as e:
        logger.error(f"❌ [Router] Ollama Error: {e}")
        raise
