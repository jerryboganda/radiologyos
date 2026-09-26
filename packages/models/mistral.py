"""Mistral chat-completions transport for bulk ingest agents (ADR 0027).

Runs on the owner's free Experiment plan (training opt-in accepted by the owner;
the library is public teaching material). Images travel inline as base64 data
URIs; the output is constrained with the agent's JSON Schema and validated by
the gateway afterwards. Requests are paced to the free tier's roughly one
request per second, and short rate limits are retried with backoff; a
persistent limit raises ``UsageLimitError`` so the gateway falls back to the
next target. The key comes from the environment and, like prompts and outputs,
is never logged (hard rule 4).
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any

import httpx

from packages.models.claude_code import ModelCall, ModelCallError, ModelResult, UsageLimitError

DEFAULT_BASE_URL = "https://api.mistral.ai/v1"
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".webp": "image/webp"}
RETRY_STATUSES = {429, 500, 502, 503, 504}
_pace_lock = threading.Lock()
_last_request = [0.0]


@dataclass(slots=True)
class MistralTransport:
    api_key_env: str = "MISTRAL_API_KEY"
    min_interval_s: float = 1.1
    retries: int = 5
    backoff_s: float = 2.0
    client: httpx.Client | None = None
    backends: tuple[str, ...] = ("mistral",)
    _sleep: Any = field(default=time.sleep, repr=False)

    def available(self) -> bool:
        return bool(os.environ.get(self.api_key_env))

    def run(self, call: ModelCall) -> ModelResult:
        key = os.environ.get(call.api_key_env or self.api_key_env, "")
        if not key:
            raise ModelCallError("mistral key is not configured")
        url = (call.base_url or DEFAULT_BASE_URL).rstrip("/") + "/chat/completions"
        body = _body(call, strict=True)
        client = self.client or httpx.Client(timeout=call.timeout_s)
        started = time.monotonic()
        try:
            response = self._post(client, url, key, body)
            if response.status_code in (400, 422):
                # Some JSON Schema keywords are rejected in strict mode: ask for
                # plain JSON instead; the gateway still validates the output.
                response = self._post(client, url, key, _body(call, strict=False))
        finally:
            if self.client is None:
                client.close()
        return _parse(response, int((time.monotonic() - started) * 1000))

    def _post(self, client: httpx.Client, url: str, key: str,
              body: dict[str, Any]) -> httpx.Response:
        headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
        for attempt in range(self.retries + 1):
            self._pace()
            try:
                response = client.post(url, headers=headers, json=body)
            except httpx.HTTPError as exc:
                if attempt == self.retries:
                    raise ModelCallError(f"mistral request failed ({type(exc).__name__})") from exc
                self._sleep(self.backoff_s * 2**attempt)
                continue
            if response.status_code not in RETRY_STATUSES or attempt == self.retries:
                return response
            retry_after = response.headers.get("retry-after", "")
            delay = float(retry_after) if retry_after.isdigit() else self.backoff_s * 2**attempt
            self._sleep(min(delay, 60.0))
        raise ModelCallError("mistral retries exhausted")  # pragma: no cover

    def _pace(self) -> None:
        with _pace_lock:
            wait = self.min_interval_s - (time.monotonic() - _last_request[0])
            if wait > 0:
                self._sleep(wait)
            _last_request[0] = time.monotonic()


def _body(call: ModelCall, strict: bool) -> dict[str, Any]:
    system = call.system_prompt
    if strict:
        response_format: dict[str, Any] = {"type": "json_schema", "json_schema": {
            "name": "output", "schema": call.output_schema, "strict": True}}
    else:
        response_format = {"type": "json_object"}
        system += ("\n\nReturn only one JSON object that validates against this JSON Schema:\n"
                   + json.dumps(call.output_schema, separators=(",", ":")))
    content: list[dict[str, Any]] = [{"type": "text", "text": call.user_prompt}]
    for name, data in call.files:
        media = IMAGE_TYPES.get(PurePath(name).suffix.lower())
        if media is None:
            raise ModelCallError("mistral transport accepts image files only")
        encoded = base64.b64encode(data).decode("ascii")
        content.append({"type": "image_url", "image_url": f"data:{media};base64,{encoded}"})
    return {"model": call.model, "temperature": 0,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": content}],
            "response_format": response_format}


def _parse(response: httpx.Response, elapsed_ms: int) -> ModelResult:
    if response.status_code == 429:
        raise UsageLimitError("mistral rate or quota limit reached")
    if response.status_code != 200:
        raise ModelCallError(f"mistral call failed (status {response.status_code})")
    try:
        payload = response.json()
        text = payload["choices"][0]["message"]["content"]
        output = json.loads(text) if isinstance(text, str) else None
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ModelCallError("mistral returned no parseable JSON") from exc
    if not isinstance(output, dict):
        raise ModelCallError("mistral returned no JSON object")
    usage = payload.get("usage") or {}
    return ModelResult(
        output=output, duration_ms=elapsed_ms, cost_usd=0.0, backend="mistral",
        usage={"input_tokens": usage.get("prompt_tokens", 0),
               "output_tokens": usage.get("completion_tokens", 0)},
    )
