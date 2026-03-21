"""
SME Research Assistant - Ollama Client

LLM client for local Ollama server with streaming support.
"""

import logging
import httpx
from typing import Iterator, Optional, Dict, Any
import json

from src.core.interfaces import LLMClient
from src.core.exceptions import LLMConnectionError, LLMTimeoutError, GenerationError

logger = logging.getLogger(__name__)


class OllamaClient(LLMClient):
    """
    LLM client for Ollama server.
    """
    
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model_name: str = "gemma:7b",
        timeout: int = 120,
        num_ctx: int = 32768
    ):
        """
        Initialize Ollama client.
        
        Args:
            base_url: Ollama server URL
            model_name: Model to use
            timeout: Request timeout in seconds
            num_ctx: Context window size
        """
        self.base_url = base_url.rstrip('/')
        self.model_name = model_name
        self.timeout = timeout
        self.num_ctx = num_ctx
    
    def _check_connection(self) -> bool:
        """Check if Ollama server is available."""
        try:
            response = httpx.get(
                f"{self.base_url}/api/tags",
                timeout=5.0
            )
            return response.status_code == 200
        except Exception:
            return False
    
    def _check_model_available(self) -> bool:
        """Check if the specified model is available."""
        try:
            response = httpx.get(
                f"{self.base_url}/api/tags",
                timeout=5.0
            )
            if response.status_code == 200:
                models = response.json().get("models", [])
                return any(m.get("name", "").startswith(self.model_name.split(":")[0]) for m in models)
        except Exception:
            pass
        return False
    
    def pull_model(self, model_name: str) -> bool:
        """
        Pull a model from the Ollama library.
        
        Args:
            model_name: Name of the model to pull
            
        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Model '{model_name}' not found. Attempting to pull...")
        try:
            with httpx.stream(
                "POST",
                f"{self.base_url}/api/pull",
                json={"model": model_name},
                timeout=None  # Disable timeout for large downloads
            ) as response:
                if response.status_code != 200:
                    logger.error(f"Failed to pull model '{model_name}': {response.status_code}")
                    return False
                
                # Consume stream to keep connection alive and log progress
                for line in response.iter_lines():
                    if line:
                        try:
                            data = json.loads(line)
                            if "status" in data:
                                # Log only major status updates to avoid spam
                                if data.get("status") in ["downloading", "processing", "verifying"]:
                                    if "total" in data and "completed" in data:
                                        percent = int((data["completed"] / data["total"]) * 100)
                                        if percent % 10 == 0: # Log every 10%
                                             logger.info(f"Pulling {model_name}: {data['status']} {percent}%")
                                else:
                                     logger.info(f"Pulling {model_name}: {data['status']}")
                        except:
                            pass
            
            logger.info(f"Successfully pulled model '{model_name}'")
            return True
        except Exception as e:
            logger.error(f"Error pulling model '{model_name}': {e}")
            return False

    def _ensure_model_exists(self, model_name: str):
        """Ensure the model exists, pulling it if necessary."""
        # Clean model name (remove tag if it's 'latest' implicit, but safest to use full name)
        # Check if available first
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=5.0)
            if response.status_code == 200:
                models = response.json().get("models", [])
                # Check for exact match or name match (ignoring tag if not specified)
                exists = any(m.get("name") == model_name or m.get("name") == f"{model_name}:latest" for m in models)
                
                if not exists:
                    # Double check partials just in case of tag mismatch logic
                    # But if user asks for "gemma:7b", we expect "gemma:7b"
                    self.pull_model(model_name)
        except Exception as e:
            logger.warning(f"Failed to check/pull model {model_name}: {e}")

    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.1,
        max_tokens: int = 4096,
        model: str = None  # Optional model override
    ) -> str:
        """
        Generate a response using chat API (better for instruction tuned models).
        
        Args:
            prompt: User prompt
            system_prompt: System prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate (num_predict)
            model: Optional model name override (uses self.model_name if None)
            
        Returns:
            Generated text
        """
        if not self._check_connection():
            raise LLMConnectionError(
                "Cannot connect to Ollama server",
                {"base_url": self.base_url}
            )
        
        # Use provided model or fall back to default
        active_model = model or self.model_name
        
        # Auto-pull if missing
        self._ensure_model_exists(active_model)
        
        logger.info(f"Using model: {active_model} (Chat Mode)")
        
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            payload = {
                "model": active_model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                    "num_ctx": self.num_ctx
                }
            }
            
            response = httpx.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout
            )
            
            if response.status_code != 200:
                raise GenerationError(
                    f"Ollama returned status {response.status_code}: {response.text}",
                    {"status": response.status_code, "response": response.text}
                )
            
            result = response.json()
            # Chat API returns 'message': {'content': ...}
            return result.get("message", {}).get("content", "")
            
        except httpx.TimeoutException:
            raise LLMTimeoutError(
                f"Ollama request timed out after {self.timeout}s",
                {"timeout": self.timeout}
            )
        except Exception as e:
            if isinstance(e, (LLMConnectionError, LLMTimeoutError, GenerationError)):
                raise
            raise GenerationError(
                f"Generation failed: {str(e)}",
                {"error": str(e)}
            )
    
    def generate_stream(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.1,
        max_tokens: int = 2000
    ) -> Iterator[str]:
        """
        Generate a streaming response.
        
        Args:
            prompt: User prompt
            system_prompt: System prompt  
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            
        Yields:
            Token chunks as they're generated
        """
        if not self._check_connection():
            raise LLMConnectionError(
                "Cannot connect to Ollama server",
                {"base_url": self.base_url}
            )
            
        # Auto-pull if missing
        self._ensure_model_exists(self.model_name)
        
        try:
            payload = {
                "model": self.model_name,
                "prompt": prompt,
                "stream": True,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                    "num_ctx": self.num_ctx
                }
            }
            
            if system_prompt:
                payload["system"] = system_prompt
            
            with httpx.stream(
                "POST",
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=self.timeout
            ) as response:
                if response.status_code != 200:
                    raise GenerationError(
                        f"Ollama returned status {response.status_code}"
                    )
                
                for line in response.iter_lines():
                    if line:
                        try:
                            data = json.loads(line)
                            if "response" in data:
                                yield data["response"]
                            if data.get("done", False):
                                break
                        except json.JSONDecodeError:
                            continue
                            
        except httpx.TimeoutException:
            raise LLMTimeoutError(
                f"Ollama stream timed out after {self.timeout}s"
            )
        except Exception as e:
            if isinstance(e, (LLMConnectionError, LLMTimeoutError, GenerationError)):
                raise
            raise GenerationError(f"Stream generation failed: {str(e)}")
    
    def chat(
        self,
        messages: list,
        temperature: float = 0.1,
        max_tokens: int = 2000,
        model: str = None  # Optional model override
    ) -> str:
        """
        Chat completion with message history.
        
        Args:
            messages: List of {"role": "user"|"assistant"|"system", "content": "..."}
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            model: Optional model name override (uses self.model_name if None)
            
        Returns:
            Assistant response
        """
        if not self._check_connection():
            raise LLMConnectionError("Cannot connect to Ollama server")
        
        # Use provided model or fall back to default
        active_model = model or self.model_name
        
        # Auto-pull if missing
        self._ensure_model_exists(active_model)
        
        try:
            
            payload = {
                "model": active_model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                    "num_ctx": self.num_ctx
                }
            }
            
            response = httpx.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout
            )
            
            if response.status_code != 200:
                raise GenerationError(f"Ollama returned status {response.status_code}")
            
            result = response.json()
            return result.get("message", {}).get("content", "")
            
        except httpx.TimeoutException:
            raise LLMTimeoutError(f"Chat request timed out after {self.timeout}s")
        except Exception as e:
            if isinstance(e, (LLMConnectionError, LLMTimeoutError, GenerationError)):
                raise
            raise GenerationError(f"Chat failed: {str(e)}")


def create_ollama_client(
    base_url: str = "http://localhost:11434",
    model_name: str = "gemma:7b",
    timeout: int = 120,
    num_ctx: int = 32768
) -> OllamaClient:
    """Factory function to create Ollama client."""
    return OllamaClient(
        base_url=base_url,
        model_name=model_name,
        timeout=timeout,
        num_ctx=num_ctx
    )
