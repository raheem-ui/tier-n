"""Groq chat wrapper that always returns validated JSON or raises LLMError."""
import json
import re
import time

from .config import settings


class LLMError(RuntimeError):
    pass


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_json_object(text: str) -> dict:
    """Parse a JSON object out of model output, tolerating code fences and chatter."""
    if not text:
        raise ValueError("empty response")
    candidates = [text.strip()]
    candidates += [m.strip() for m in _FENCE.findall(text)]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for c in candidates:
        try:
            obj = json.loads(c)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise ValueError("no JSON object found in response")


class GroqJSON:
    def __init__(self, api_key: str | None = None, model: str | None = None, client=None):
        self.model = model or settings.groq_model
        if client is not None:
            self.client = client
        else:
            key = api_key or settings.groq_api_key
            if not key:
                raise LLMError("GROQ_API_KEY is not set")
            from groq import Groq

            self.client = Groq(api_key=key)

    def complete(self, system: str, user: str, required_keys: tuple[str, ...] = (), attempts: int = 3) -> dict:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.2,
                    response_format={"type": "json_object"},
                )
                text = resp.choices[0].message.content or ""
            except Exception as e:  # rate limits, json_validate_failed, network
                last_error = e
                time.sleep(min(2**attempt, 4))
                continue
            try:
                obj = parse_json_object(text)
                missing = [k for k in required_keys if k not in obj]
                if missing:
                    raise ValueError(f"missing keys: {missing}")
                return obj
            except ValueError as e:
                last_error = e
                messages = messages[:2] + [
                    {"role": "assistant", "content": text[:4000]},
                    {"role": "user", "content": f"That response was invalid ({e}). Reply with only the corrected JSON object."},
                ]
        raise LLMError(f"LLM failed after {attempts} attempts: {last_error}")
