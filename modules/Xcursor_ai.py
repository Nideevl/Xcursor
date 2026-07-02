"""Xcursor AI integration with Groq primary + Ollama fallback, streaming and caching"""
import json
import threading
import time
import requests
import os
from modules.keyword_cache import KeywordCache
from modules.keyword_extractor import KeywordExtractor

class XcursorAI:
    def __init__(self, cache=None, groq_api_key=None):
        # Groq configuration (primary)
        self.groq_api_key = groq_api_key or os.getenv("GROQ_API_KEY")
        self.groq_base_url = "https://api.groq.com/openai/v1"
        self.groq_model = "qwen/qwen3.6-27b"  # Primary model
        self.groq_available = bool(self.groq_api_key)
        
        # Ollama configuration (fallback)
        self.ollama_base_url = "http://localhost:11434"
        self.ollama_model = "qwen3:4b-instruct"
        self.ollama_available = self.check_ollama_connection()
        
        # Caching
        self.cache = cache or KeywordCache()
        self.extractor = KeywordExtractor()
        
        # State tracking
        self.last_service = None  # Track which service was used
        
        # ✅ Add these missing attributes
        self.connected = self.groq_available or self.ollama_available
        self.model = self.groq_model if self.groq_available else self.ollama_model
        self.current_model = self.model  # Alias for clarity
        
        self._log_init()
    
    # ✅ ADD THIS METHOD - FIXES THE ERROR
    def set_ollama_model(self, model_name):
        """Set the Ollama model to use for fallback"""
        self.ollama_model = model_name
        print(f"🔄 Ollama model set to: {model_name}")
    
    def _log_init(self):
        """Log initialization status"""
        print("=" * 60)
        print("🚀 Xcursor AI Initialization")
        print("=" * 60)
        if self.groq_available:
            print(f"✅ Groq API: Connected (model: {self.groq_model})")
        else:
            print("⚠️  Groq API: Not configured (set GROQ_API_KEY)")
        
        if self.ollama_available:
            print(f"✅ Ollama: Connected (model: {self.ollama_model})")
        else:
            print("⚠️  Ollama: Not available at http://localhost:11434")
        
        if self.connected:
            print(f"✅ AI Service: Ready (using: {self.current_model})")
        else:
            print("❌ AI Service: No connection available")
        print("=" * 60)
    
    def check_ollama_connection(self):
        """Check if local Ollama is running"""
        try:
            response = requests.get(f"{self.ollama_base_url}/api/tags", timeout=2)
            return response.status_code == 200
        except:
            return False
    
    def analyze_streaming(self, text, token_callback, done_callback, model=None, conversation_history=None):
        """
        Stream AI response with conversation history.
        Uses the selected model from dropdown.
        """
        # If a specific model is passed from dropdown
        if model:
            if model == "qwen3.6-27b":
                self.groq_model = "qwen/qwen3.6-27b"
                print(f"\n🔵 Using Groq model: {self.groq_model}")
                success = self._analyze_groq(text, token_callback, done_callback, conversation_history)
                if success:
                    self.last_service = "Groq"
                    return
                else:
                    # If Groq fails, try Ollama fallback
                    print(f"⚠️ Groq failed, using Ollama fallback...")
                    self._analyze_ollama(text, token_callback, done_callback, self.ollama_model, conversation_history)
                    self.last_service = "Ollama"
                    return
            else:
                # Any non-Groq dropdown entry is an Ollama model
                self.ollama_model = model
                print(f"\n🟢 Using Ollama model: {self.ollama_model}")
                self._analyze_ollama(text, token_callback, done_callback, self.ollama_model, conversation_history)
                self.last_service = "Ollama"
                return

        # Default behavior (if no model specified)
        if self.groq_available:
            print(f"\n🔵 Attempting Groq ({self.groq_model})...")
            success = self._analyze_groq(text, token_callback, done_callback, conversation_history)
            if success:
                self.last_service = "Groq"
                return

        # Fallback to Ollama
        print(f"🔴 Falling back to Ollama (local) using: {self.ollama_model}...")
        self._analyze_ollama(text, token_callback, done_callback, self.ollama_model, conversation_history)
        self.last_service = "Ollama"
        
    def _analyze_groq(self, text, token_callback, done_callback, conversation_history):
        """
        Attempt streaming via Groq API.
        Returns True if successful, False otherwise.
        Filters out <think>...</think> reasoning blocks from Qwen models,
        and strips leading whitespace left behind around the tags.
        """
        try:
            # Build messages for Groq (OpenAI-compatible format)
            messages = []
            
            if conversation_history:
                for role, msg in conversation_history:
                    messages.append({
                        "role": "user" if role == "user" else "assistant",
                        "content": msg
                    })
            
            messages.append({
                "role": "user",
                "content": f"{text}\n\nProvide a helpful analysis or answer. Keep it brief and to the point."
            })
            
            # Groq API call with streaming
            response = requests.post(
                f"{self.groq_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.groq_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.groq_model,
                    "messages": messages,
                    "stream": True,
                    "temperature": 0.7,
                    "max_tokens": 1024,
                },
                timeout=30,
                stream=True
            )
            
            # Handle rate limit (429)
            if response.status_code == 429:
                retry_after = response.headers.get("retry-after", "unknown")
                print(f"⚠️  Rate limit (429) from Groq. Retry after: {retry_after}s")
                token_callback(f"⚠️ Groq rate limited. Retrying with local model...")
                return False
            
            # Handle other HTTP errors
            if response.status_code != 200:
                print(f"❌ Groq error: {response.status_code}")
                print(f"Response: {response.text}")
                token_callback(f"❌ Groq error: {response.status_code}")
                return False
            
            # Stream tokens, filtering out <think>...</think> blocks
            full_response = ""
            buffer = ""
            in_thinking = False
            emitted_real_content = False  # tracks whether we've sent any non-whitespace yet
            TAG_BUFFER_SIZE = 10  # enough to safely detect "<think>" / "</think>" split across chunks

            def emit(chunk):
                """Emit a chunk, stripping leading whitespace until real content starts."""
                nonlocal full_response, emitted_real_content
                if not chunk:
                    return
                if not emitted_real_content:
                    stripped = chunk.lstrip()
                    if not stripped:
                        # entirely whitespace so far — nothing to emit yet
                        return
                    chunk = stripped
                    emitted_real_content = True
                full_response += chunk
                token_callback(chunk)

            for line in response.iter_lines():
                if line:
                    line = line.decode('utf-8') if isinstance(line, bytes) else line
                    if line.startswith("data: "):
                        line = line[6:]
                    
                    if line.strip() == "[DONE]":
                        break
                    
                    try:
                        data = json.loads(line)
                        delta = data.get("choices", [{}])[0].get("delta", {})
                        token = delta.get("content", "")
                        if not token:
                            continue

                        buffer += token

                        # Process buffer, handling tag boundaries safely
                        while True:
                            if not in_thinking:
                                start_idx = buffer.find("<think>")
                                if start_idx == -1:
                                    # No opening tag found — flush all but last few chars
                                    # (in case a tag is split across chunks)
                                    if len(buffer) > TAG_BUFFER_SIZE:
                                        chunk = buffer[:-TAG_BUFFER_SIZE]
                                        emit(chunk)
                                        buffer = buffer[-TAG_BUFFER_SIZE:]
                                    break
                                else:
                                    # Emit everything before <think>, then enter thinking mode
                                    chunk = buffer[:start_idx]
                                    emit(chunk)
                                    buffer = buffer[start_idx + len("<think>"):]
                                    in_thinking = True
                            else:
                                end_idx = buffer.find("</think>")
                                if end_idx == -1:
                                    # Still inside thinking block — discard, keep tail for tag detection
                                    if len(buffer) > TAG_BUFFER_SIZE:
                                        buffer = buffer[-TAG_BUFFER_SIZE:]
                                    break
                                else:
                                    # Discard thinking content, exit thinking mode
                                    buffer = buffer[end_idx + len("</think>"):]
                                    in_thinking = False

                    except json.JSONDecodeError:
                        pass
            
            # Flush any remaining non-thinking buffer content
            if not in_thinking and buffer:
                emit(buffer)
            
            if full_response and not full_response.endswith('\n'):
                token_callback('\n')
            
            done_callback()
            return True
        
        except requests.exceptions.Timeout:
            print("⏱️  Groq timeout")
            return False
        except Exception as e:
            print(f"❌ Groq error: {str(e)}")
            return False 
        
    def _analyze_ollama(self, text, token_callback, done_callback, model=None, conversation_history=None):
        """
        Fallback streaming via local Ollama.
        """
        if not self.ollama_available:
            token_callback("⚠️ Xcursor not connected. Start Ollama: ollama serve")
            done_callback()
            return
        
        if model is None:
            model = self.ollama_model
        
        model_name = model.split()[0]
        
        try:
            # Build prompt with history
            if conversation_history:
                history_text = ""
                for role, msg in conversation_history:
                    if role == "user":
                        history_text += f"User: {msg}\n\n"
                    else:
                        history_text += f"Assistant: {msg}\n\n"
                
                prompt = f"""{history_text}User: {text}

TEXT:
{text}

Provide a helpful analysis or answer. Keep it brief and to the point."""
            else:
                prompt = f"""Analyze the following text and provide a helpful response:

TEXT:
{text}

Provide a helpful analysis or answer. Keep it brief and to the point."""
            
            response = requests.post(
                f"{self.ollama_base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": True,
                    "temperature": 0.7,
                    "keep_alive": -1,
                },
                timeout=200,
                stream=True
            )
            
            if response.status_code == 200:
                full_response = ""
                for line in response.iter_lines():
                    if line:
                        try:
                            data = json.loads(line)
                            token = data.get("response", "")
                            if token:
                                full_response += token
                                token_callback(token)
                        except json.JSONDecodeError:
                            pass
                
                if full_response and not full_response.endswith('\n'):
                    token_callback('\n')
                
                done_callback()
            else:
                token_callback(f"❌ Ollama error: {response.status_code}")
                done_callback()
        
        except requests.exceptions.Timeout:
            token_callback("⏱️ Ollama timeout.")
            done_callback()
        except Exception as e:
            token_callback(f"❌ Error: {str(e)}")
            done_callback()
    
    def get_keyword_definition(self, keyword):
        """
        Get keyword definition with Groq primary, Ollama fallback.
        """
        cached = self.cache.get(keyword)
        if cached:
            return cached, True
        
        prompt = f"""Define the word '{keyword}' in one sentence, concise and clear."""
        
        # Try Groq first
        if self.groq_available:
            try:
                response = requests.post(
                    f"{self.groq_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.groq_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.groq_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.5,
                        "max_tokens": 100,
                    },
                    timeout=10
                )
                
                if response.status_code == 200:
                    definition = response.json()["choices"][0]["message"]["content"].strip()
                    self.cache.set(keyword, definition)
                    return definition, False
                elif response.status_code == 429:
                    print(f"⚠️  Groq rate limit on keyword lookup, falling back to Ollama")
            except:
                pass
        
        # Fallback to Ollama
        if self.ollama_available:
            try:
                response = requests.post(
                    f"{self.ollama_base_url}/api/generate",
                    json={
                        "model": self.ollama_model,
                        "prompt": prompt,
                        "stream": False,
                        "temperature": 0.5,
                        "keep_alive": -1,
                    },
                    timeout=30
                )
                if response.status_code == 200:
                    definition = response.json().get("response", "").strip()
                    self.cache.set(keyword, definition)
                    return definition, False
            except:
                pass
        
        return f"[Definition not available]", True