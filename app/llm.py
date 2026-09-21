"""Pluggable LLM layer.

Any OpenAI-compatible /chat/completions endpoint: Gemini (via its OpenAI
compatibility URL), Ollama, LM Studio, vLLM... Switch by changing
LLM_BASE_URL / LLM_MODEL / LLM_API_KEY. Nothing else in the app changes.

Every call fails safe (returns None) so callers can fall back to keywords.
"""
from typing import List, Optional

import httpx

from .config import settings


class BaseLLM:
    def classify(self, text: str, labels: List[str]) -> Optional[str]:
        raise NotImplementedError

    def chat(self, messages: List[dict], temperature: float = 0.3,
             timeout: float = 30, use_fallback: bool = True) -> Optional[str]:
        """Return the model's reply text, or None on any failure."""
        raise NotImplementedError


class NullLLM(BaseLLM):
    """Used when LLM_ENABLED=false — always defers to keyword fallback."""
    def classify(self, text: str, labels: List[str]) -> Optional[str]:
        return None

    def chat(self, messages: List[dict], temperature: float = 0.3,
             timeout: float = 30, use_fallback: bool = True) -> Optional[str]:
        return None


class LocalLLM(BaseLLM):
    """Any OpenAI-compatible /chat/completions endpoint."""

    def __init__(self, base_url: str, model: str, api_key: str):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.api_key = api_key
        self.last_error = ""
        # Reasoning models (e.g. OpenAI GPT-5.x) reject custom temperatures; learned on first 400.
        self._no_temperature = set()

    def chat(self, messages: List[dict], temperature: float = 0.3,
             timeout: float = 30, use_fallback: bool = True) -> Optional[str]:
        fallback = settings.LLM_FALLBACK_MODEL if use_fallback else ""
        if fallback and fallback != self.model:
            # Hosted models return 503 under load; give the primary a short leash.
            primary_timeout = min(timeout, settings.LLM_PRIMARY_TIMEOUT)
            return (self._call(self.model, messages, temperature, primary_timeout)
                    or self._call(fallback, messages, temperature, timeout))
        return self._call(self.model, messages, temperature, timeout)

    def _call(self, model: str, messages: List[dict], temperature: float,
              timeout: float) -> Optional[str]:
        body = {"model": model, "messages": messages}
        if model not in self._no_temperature:
            body["temperature"] = temperature
        if settings.LLM_REASONING_EFFORT:
            body["reasoning_effort"] = settings.LLM_REASONING_EFFORT
        self.last_error = ""
        try:
            resp = self._post(body, timeout)
            if (resp.status_code == 400 and "temperature" in resp.text
                    and "temperature" in body):
                self._no_temperature.add(model)
                del body["temperature"]
                resp = self._post(body, timeout)
            if resp.status_code >= 400:
                self.last_error = f"{resp.status_code} {resp.text[:1000]}"
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return content.strip() if content else None
        except Exception as e:
            self.last_error = self.last_error or f"{type(e).__name__}: {e}"
            print(f"[llm] {model} call failed: {type(e).__name__}: {str(e)[:120]}")
            return None

    def _post(self, body: dict, timeout: float) -> httpx.Response:
        return httpx.post(
            self.url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=body,
            timeout=timeout,
        )

    def classify(self, text: str, labels: List[str]) -> Optional[str]:
        label_list = ", ".join(labels)
        system = (
            "You are a strict text classifier. Given a business description, "
            f"reply with EXACTLY ONE of these labels and nothing else: {label_list}. "
            "No explanation, no punctuation."
        )
        answer = self.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": text}],
            temperature=0, timeout=20,
        )
        if not answer:
            return None  # fail safe -> caller uses keyword fallback

        # Validate the model actually returned one of our labels.
        answer_low = answer.lower()
        for label in labels:
            if label.lower() == answer_low or label.lower() in answer_low:
                return label
        return None


def get_llm() -> BaseLLM:
    if not settings.LLM_ENABLED:
        return NullLLM()
    return LocalLLM(settings.LLM_BASE_URL, settings.LLM_MODEL, settings.LLM_API_KEY)
