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
        self._groq_client = None
        self._provider = config.LLM_PROVIDER

    def _get_groq_client(self):
        if self._groq_client is not None:
            return self._groq_client
        try:
            from groq import Groq
            if self.config.GROQ_API_KEY:
                self._groq_client = Groq(api_key=self.config.GROQ_API_KEY)
                logger.info("LLM Gateway: initialized Groq client (%s)", self.config.GROQ_MODEL)
                return self._groq_client
        except Exception as e:
            logger.warning("Groq client init error: %s", e)
        return None

    def _call_groq(self, messages: list, model: str, temperature: float = 0.1) -> str:
        client = self._get_groq_client()
        if client is None:
            raise RuntimeError("Groq client not available or GROQ_API_KEY not configured")

        active_model = getattr(self, "_working_groq_model", model)
        candidate_models = [active_model, "openai/gpt-oss-120b", "openai/gpt-oss-20b", "allam-2-7b", "qwen/qwen3.8-27b"]
        seen_models = set()

        last_error = None
        for m in candidate_models:
            if m in seen_models:
                continue
            seen_models.add(m)
            try:
                response = client.chat.completions.create(
                    model=m,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=4096,
                )
                self._working_groq_model = m
                return response.choices[0].message.content or ""
            except Exception as e:
                last_error = e
                logger.warning("Groq model '%s' failed (%s), trying next candidate", m, e)
                continue

        if last_error:
            raise last_error
        raise RuntimeError("No Groq models available")

    def _call_gemini(self, messages: list, temperature: float = 0.1) -> str:
        import httpx

        api_key = self.config.GEMINI_API_KEY
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not configured")

        model = self.config.GEMINI_MODEL or "gemini-2.5-flash"
        model_name = model.split("models/")[-1]

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"

        contents = []
        system_instructions = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_instructions.append(content)
            elif role == "assistant":
                contents.append({"role": "model", "parts": [{"text": content}]})
            else:
                contents.append({"role": "user", "parts": [{"text": content}]})

        if system_instructions:
            sys_text = "\n\n".join(system_instructions)
            if contents and contents[0]["role"] == "user":
                contents[0]["parts"][0]["text"] = f"[System Instructions]\n{sys_text}\n\n{contents[0]['parts'][0]['text']}"
            else:
                contents.insert(0, {"role": "user", "parts": [{"text": f"[System Instructions]\n{sys_text}"}]})

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": 4096,
            },
        }

        resp = httpx.post(url, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts)

    def _call_ollama(self, messages: list, temperature: float = 0.1, json_mode: bool = False) -> str:
        import httpx
        base_url = (self.config.OLLAMA_BASE_URL or "http://localhost:11434").rstrip("/")
        payload = {
            "model": self.config.OLLAMA_MODEL or "mistral",
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if json_mode:
            payload["format"] = "json"

        resp = httpx.post(f"{base_url}/api/chat", json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "")

    def complete(
        self,
        messages: list,
        temperature: float = 0.1,
        retries: int = 2,
        json_mode: bool = False,
    ) -> Optional[str]:
        """
        Send a chat completion request with provider prioritization and fallback:
        Prioritizes the provider set in LLM_PROVIDER ('ollama', 'groq', or 'gemini').
        """
        provider = (self.config.LLM_PROVIDER or "ollama").lower()
        if provider == "ollama":
            order = ["ollama", "groq", "gemini"]
        elif provider == "gemini":
            order = ["gemini", "groq", "ollama"]
        else:
            order = ["groq", "ollama", "gemini"]

        for prov in order:
            if prov == "ollama" and (self.config.OLLAMA_BASE_URL or provider == "ollama"):
                try:
                    res = self._call_ollama(messages, temperature, json_mode=json_mode)
                    if res:
                        return res
                except Exception as e:
                    logger.warning("Ollama provider failed (%s), trying next fallback", e)

            elif prov == "groq" and self.config.GROQ_API_KEY:
                for attempt in range(retries + 1):
                    try:
                        return self._call_groq(messages, self.config.GROQ_MODEL, temperature)
                    except Exception as e:
                        logger.warning("Groq attempt %d failed: %s", attempt + 1, e)
                        if attempt < retries:
                            time.sleep(1)

            elif prov == "gemini" and self.config.GEMINI_API_KEY:
                try:
                    return self._call_gemini(messages, temperature)
                except Exception as e:
                    logger.warning("Gemini provider failed: %s", e)

        logger.error("All configured LLM providers failed or unavailable.")
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
        import re

        system_instruction = (
            f"\n\nYou MUST respond with valid JSON that matches this schema: "
            f"{response_model.model_json_schema()}\n"
            f"Respond ONLY with raw JSON, no markdown, no explanation."
        )

        augmented = list(messages)
        augmented.append({"role": "system", "content": system_instruction})

        for attempt in range(retries + 1):
            raw = self.complete(augmented, temperature=temperature, retries=0, json_mode=True)
            if raw is None:
                return None
            try:
                text = raw.strip()
                match = re.search(r"\{.*\}", text, re.DOTALL)
                if match:
                    data = json.loads(match.group(0))
                else:
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
