#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemini-3.5-flash")
    args = ap.parse_args()
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY or GOOGLE_API_KEY missing")
    model = args.model.split("/", 1)[-1]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = json.dumps({"contents":[{"role":"user","parts":[{"text":"Reply with JSON: {\\\"ok\\\":true}"}]}],"generationConfig":{"responseMimeType":"application/json","maxOutputTokens":32}}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type":"application/json","x-goog-api-key":key}, method="POST")
    t = time.monotonic()
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = json.loads(resp.read().decode())
    text = "".join(p.get("text","") for p in raw["candidates"][0]["content"]["parts"])
    print(json.dumps({"model": model, "latency_ms": int((time.monotonic()-t)*1000), "text": text, "usage": raw.get("usageMetadata", {})}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
