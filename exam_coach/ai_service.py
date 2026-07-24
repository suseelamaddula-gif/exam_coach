import os
import time
import logging
import hashlib
import json
from collections import OrderedDict

# Setup logging
logger = logging.getLogger(__name__)

# Try importing AI providers
try:
    import google.generativeai as genai
except ImportError:
    genai = None

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    from groq import Groq
    from groq._base_client import AuthenticationError as GroqAuthError
except ImportError:
    Groq = None
    GroqAuthError = None

class SimpleLRUCache:
    def __init__(self, capacity=100, ttl_seconds=3600):
        self.cache = OrderedDict()
        self.capacity = capacity
        self.ttl = ttl_seconds

    def get(self, key):
        if key not in self.cache:
            return None
        value, timestamp = self.cache[key]
        if time.time() - timestamp > self.ttl:
            del self.cache[key]
            return None
        # Move to end to represent recently used
        self.cache.move_to_end(key)
        return value

    def set(self, key, value):
        if key in self.cache:
            del self.cache[key]
        elif len(self.cache) >= self.capacity:
            self.cache.popitem(last=False)
        self.cache[key] = (value, time.time())

class AIService:
    def __init__(self):
        self.cache = SimpleLRUCache(capacity=200, ttl_seconds=3600)
        self.active_provider = None
        self._init_providers()

    def _init_providers(self):
        # Validate and initialize active AI providers
        self.gemini_key = os.environ.get("GEMINI_API_KEY")
        self.openai_key = os.environ.get("OPENAI_API_KEY")
        self.groq_key = os.environ.get("GROQ_API_KEY")
        
        # Check defaults or placeholders
        if self.gemini_key == "your_gemini_api_key_here":
            self.gemini_key = None
        if self.openai_key == "your_openai_api_key_here":
            self.openai_key = None
        if self.groq_key == "your_groq_api_key_here":
            self.groq_key = None

        if self.gemini_key and genai:
            genai.configure(api_key=self.gemini_key)
            self.active_provider = "gemini"
            self.model_name = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
            logger.info("AIService initialized with Google Gemini (%s)", self.model_name)
        elif self.openai_key and OpenAI:
            self.openai_client = OpenAI(api_key=self.openai_key)
            self.active_provider = "openai"
            self.model_name = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
            logger.info("AIService initialized with OpenAI (%s)", self.model_name)
        elif self.groq_key and Groq:
            self.groq_client = Groq(api_key=self.groq_key)
            self.active_provider = "groq"
            self.model_name = os.environ.get("AI_MODEL", "llama-3.3-70b-versatile")
            logger.info("AIService initialized with Groq (%s)", self.model_name)
        else:
            logger.warning("No active AI provider API key found. AI requests will use local fallbacks.")
            self.active_provider = None

    def is_configured(self):
        return self.active_provider is not None

    def get_status(self):
        return {
            "ai_configured": self.is_configured(),
            "provider": self.active_provider,
            "model": getattr(self, "model_name", "None")
        }

    def _generate_cache_key(self, system_prompt, user_prompt, history=None):
        hash_obj = hashlib.md5()
        hash_obj.update((system_prompt or "").encode("utf-8"))
        hash_obj.update((user_prompt or "").encode("utf-8"))
        if history:
            hash_obj.update(json.dumps(history).encode("utf-8"))
        return hash_obj.hexdigest()

    def generate_text(self, system_prompt, user_prompt, history=None, temperature=0.7):
        if not self.is_configured():
            return "[AI_UNAVAILABLE] AI client not configured. Provide an API key."

        cache_key = self._generate_cache_key(system_prompt, user_prompt, history)
        cached_val = self.cache.get(cache_key)
        if cached_val:
            logger.debug("AIService cache hit for key: %s", cache_key)
            return cached_val

        # Execute call with retries
        for attempt in range(3):
            try:
                result = self._call_provider_api(system_prompt, user_prompt, history, temperature)
                self.cache.set(cache_key, result)
                return result
            except Exception as e:
                logger.warning("AIService call failed (attempt %d/3): %s", attempt + 1, e)
                if attempt == 2:
                    logger.exception("All attempts failed in AIService.generate_text")
                    return f"[AI_ERROR] AI call failed: {str(e)}"
                time.sleep(2 ** attempt)  # exponential backoff

    def _call_provider_api(self, system_prompt, user_prompt, history=None, temperature=0.7):
        if self.active_provider == "gemini":
            # Gemini generation
            model = genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=system_prompt
            )
            # Adapt history
            contents = []
            if history:
                for msg in history:
                    role = "user" if msg["role"] == "user" else "model"
                    contents.append({"role": role, "parts": [msg["content"]]})
            contents.append({"role": "user", "parts": [user_prompt]})
            
            response = model.generate_content(
                contents,
                generation_config=genai.types.GenerationConfig(temperature=temperature)
            )
            return response.text

        elif self.active_provider == "openai":
            # OpenAI generation
            messages = [{"role": "system", "content": system_prompt}]
            if history:
                for msg in history:
                    messages.append({"role": msg["role"], "content": msg["content"]})
            messages.append({"role": "user", "content": user_prompt})

            response = self.openai_client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=temperature
            )
            return response.choices[0].message.content

        elif self.active_provider == "groq":
            # Groq generation
            messages = [{"role": "system", "content": system_prompt}]
            if history:
                for msg in history:
                    messages.append({"role": msg["role"], "content": msg["content"]})
            messages.append({"role": "user", "content": user_prompt})

            response = self.groq_client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=temperature
            )
            return response.choices[0].message.content

    def generate_stream(self, system_prompt, user_prompt, history=None, temperature=0.7):
        """Yields chunks of text for streaming."""
        if not self.is_configured():
            yield "[AI_UNAVAILABLE]"
            return

        try:
            if self.active_provider == "gemini":
                model = genai.GenerativeModel(
                    model_name=self.model_name,
                    system_instruction=system_prompt
                )
                contents = []
                if history:
                    for msg in history:
                        role = "user" if msg["role"] == "user" else "model"
                        contents.append({"role": role, "parts": [msg["content"]]})
                contents.append({"role": "user", "parts": [user_prompt]})

                response = model.generate_content(
                    contents,
                    generation_config=genai.types.GenerationConfig(temperature=temperature),
                    stream=True
                )
                for chunk in response:
                    if chunk.text:
                        yield chunk.text

            elif self.active_provider == "openai":
                messages = [{"role": "system", "content": system_prompt}]
                if history:
                    for msg in history:
                        messages.append({"role": msg["role"], "content": msg["content"]})
                messages.append({"role": "user", "content": user_prompt})

                stream = self.openai_client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    temperature=temperature,
                    stream=True
                )
                for chunk in stream:
                    content = chunk.choices[0].delta.content
                    if content:
                        yield content

            elif self.active_provider == "groq":
                messages = [{"role": "system", "content": system_prompt}]
                if history:
                    for msg in history:
                        messages.append({"role": msg["role"], "content": msg["content"]})
                messages.append({"role": "user", "content": user_prompt})

                stream = self.groq_client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    temperature=temperature,
                    stream=True
                )
                for chunk in stream:
                    content = chunk.choices[0].delta.content
                    if content:
                        yield content

        except Exception as e:
            logger.exception("Error in AIService stream generation")
            yield f"\n[AI_ERROR] Stream interrupted: {str(e)}"

    def get_embeddings(self, text_list):
        """Generates list of embeddings (float vectors) for input strings."""
        if not self.is_configured():
            return None

        try:
            if self.active_provider == "gemini" and self.gemini_key:
                # Use Gemini embedding API
                response = genai.embed_content(
                    model="models/text-embedding-004",
                    content=text_list,
                    task_type="retrieval_document"
                )
                if isinstance(text_list, str):
                    return response.get("embedding", [])
                return [item for item in response.get("embedding", [])]

            elif self.active_provider == "openai" and self.openai_key:
                # Use OpenAI embedding API
                response = self.openai_client.embeddings.create(
                    model="text-embedding-3-small",
                    input=text_list
                )
                if isinstance(text_list, str):
                    return response.data[0].embedding
                return [item.embedding for item in response.data]

        except Exception as e:
            logger.exception("Failed to generate embedding via active provider API")
            
        return None
