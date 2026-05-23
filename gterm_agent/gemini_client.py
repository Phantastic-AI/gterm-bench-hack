from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .redaction import redact_text


@dataclass
class GeminiResponse:
    text: str
    usage: dict[str, Any]
    raw: dict[str, Any]
    latency_ms: int


class GeminiClient:
    def __init__(self, model: str = "gemini-3.5-flash", api_key: str | None = None, timeout_sec: int = 120):
        self.model = model.split("/", 1)[-1] if model.startswith("google/") else model
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self.timeout_sec = timeout_sec
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY or GOOGLE_API_KEY is required")

    @property
    def endpoint(self) -> str:
        return f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"

    def generate(self, contents: list[dict[str, Any]], *, temperature: float = 0.2, max_output_tokens: int = 4096, retries: int = 3) -> GeminiResponse:
        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens,
                "responseMimeType": "application/json",
            },
        }
        data = json.dumps(payload).encode("utf-8")
        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            req = urllib.request.Request(
                self.endpoint,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": self.api_key,
                },
                method="POST",
            )
            started = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                    raw = json.loads(resp.read().decode("utf-8"))
                latency_ms = int((time.monotonic() - started) * 1000)
                text = _extract_text(raw)
                return GeminiResponse(text=text, usage=raw.get("usageMetadata") or {}, raw=raw, latency_ms=latency_ms)
            except urllib.error.HTTPError as e:
                body = redact_text(e.read().decode("utf-8", errors="replace"), max_chars=4000)
                last_error = RuntimeError(f"Gemini HTTP {e.code}: {body}")
                if e.code < 500 and e.code not in (408, 429):
                    break
            except Exception as e:  # noqa: BLE001 - preserve API failure evidence
                last_error = e
            if attempt < retries:
                time.sleep(min(2 ** attempt, 10))
        raise RuntimeError(f"Gemini generate failed after {retries} attempts: {last_error}")


def _extract_text(raw: dict[str, Any]) -> str:
    candidates = raw.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"Gemini response had no candidates: {redact_text(json.dumps(raw)[:2000])}")
    parts = candidates[0].get("content", {}).get("parts", [])
    texts = [p.get("text", "") for p in parts if isinstance(p, dict)]
    text = "".join(texts).strip()
    if not text:
        raise RuntimeError(f"Gemini response had no text: {redact_text(json.dumps(raw)[:2000])}")
    return text
