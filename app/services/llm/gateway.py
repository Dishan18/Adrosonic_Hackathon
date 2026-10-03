"""
LLM Gateway: provider-agnostic interface.
Primary: Groq Llama 3.3 70B
Fallback: Ollama local model
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional, Type

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class LLMGateway:
    """
    Provider-agnostic LLM interface.
    Swappable between Groq, Ollama, or OpenAI without changing agent logic.
    """

    def __init__(self):
        from app.config import config
        self.config = config
        self._client = None
        self._provider = config.LLM_PROVIDER

    def _get_client(self):
        if self._client is not None:
            return self._client

        if self._provider == "groq":
            try:
                from groq import Groq
                self._client = Groq(api_key=self.config.GROQ_API_KEY)
                logger.info("LLM Gateway: using Groq (%s)", self.config.GROQ_MODEL)
            except Exception as e:
                logger.warning("Groq init failed: %s — falling back to Ollama", e)
                self._provider = "ollama"
                return self._get_ollama_client()
        elif self._provider == "ollama":
            return self._get_ollama_client()
        else:
            raise ValueError(f"Unknown LLM provider: {self._provider}")

        return self._client

    def _get_ollama_client(self):
        try:
            import httpx
            # Store a simple marker; actual calls use httpx
            self._client = {"type": "ollama", "base_url": self.config.OLLAMA_BASE_URL}
            logger.info("LLM Gateway: using Ollama at %s", self.config.OLLAMA_BASE_URL)
            return self._client
        except Exception as e:
            logger.error("Ollama init failed: %s", e)
            return None

    def _call_groq(self, messages: list, model: str, temperature: float = 0.1) -> str:
        client = self._get_client()
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=4096,
        )
        return response.choices[0].message.content or ""

    def _call_ollama(self, messages: list, temperature: float = 0.1) -> str:
        import httpx
        base_url = self.config.OLLAMA_BASE_URL
        payload = {
            "model": self.config.OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        resp = httpx.post(f"{base_url}/api/chat", json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json()["message"]["content"]

    def complete(
        self,
        messages: list,
        temperature: float = 0.1,
        retries: int = 2,
    ) -> Optional[str]:
        """
        Send a chat completion request.
        Returns None if the LLM is unavailable after retries.
        """
        for attempt in range(retries + 1):
            try:
                client = self._get_client()
                if client is None:
                    return None
                if self._provider == "groq":
                    return self._call_groq(messages, self.config.GROQ_MODEL, temperature)
                elif self._provider == "ollama":
                    return self._call_ollama(messages, temperature)
            except Exception as e:
                logger.warning("LLM attempt %d failed: %s", attempt + 1, e)
                if attempt < retries:
                    time.sleep(2 ** attempt)

        logger.error("LLM unavailable after %d attempts", retries + 1)
        return None

    def complete_structured(
        self,
        messages: list,
        response_model: Type[BaseModel],
        temperature: float = 0.1,
        retries: int = 2,
    ) -> Optional[BaseModel]:
        """
        Call LLM and parse response as a Pydantic model.
        Returns None if unavailable or validation fails repeatedly.
        """
        system_instruction = (
            f"\n\nYou MUST respond with valid JSON that matches this schema: "
            f"{response_model.model_json_schema()}\n"
            f"Respond ONLY with raw JSON, no markdown, no explanation."
        )

        # Append schema instruction to last system message or add new one
        augmented = list(messages)
        augmented.append({"role": "system", "content": system_instruction})

        for attempt in range(retries + 1):
            raw = self.complete(augmented, temperature=temperature, retries=0)
            if raw is None:
                return None
            try:
                # Strip markdown code fences if present
                text = raw.strip()
                if text.startswith("```"):
                    text = text.split("```")[1]
                    if text.startswith("json"):
                        text = text[4:]
                data = json.loads(text)
                return response_model.model_validate(data)
            except Exception as e:
                logger.warning(
                    "Structured parse attempt %d failed: %s\nRaw: %.200s",
                    attempt + 1, e, raw,
                )
                if attempt < retries:
                    augmented.append({
                        "role": "user",
                        "content": f"Your previous response was invalid JSON. Error: {e}. Please try again with valid JSON only.",
                    })

        logger.error("Failed to get valid structured response after %d attempts", retries + 1)
        return None

    @property
    def available(self) -> bool:
        from app.config import config
        return config.is_llm_available()


# Singleton
_gateway: Optional[LLMGateway] = None


def get_llm() -> LLMGateway:
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway
