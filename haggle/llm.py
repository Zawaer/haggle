"""Thin async wrapper around the Gemini Interactions API.

Every LLM call in haggle goes through `ask_json`: structured JSON output against a schema,
retries with backoff, a fallback model on 503s, a global concurrency limit and a per-hunt
call budget (Google's hackathon accounts flag "thousands of requests" as abuse).
"""
import asyncio
import json
import logging
import threading
import time

from google import genai

from . import config, limits

log = logging.getLogger("haggle.llm")
_client = None
_client_lock = threading.Lock()
_sem = asyncio.Semaphore(config.MAX_PARALLEL_LLM)


def client():
    """One shared client. Created under a lock: threads racing to create it used to replace each other's
    client, and the garbage-collected one closed its HTTP connection mid-request."""
    global _client
    with _client_lock:
        if _client is None:
            _client = genai.Client()
        return _client


class Budget:
    """Counts calls for one hunt and refuses to exceed the cap."""

    def __init__(self, cap=config.MAX_LLM_CALLS_PER_HUNT):
        self.cap, self.calls, self.seconds = cap, 0, 0.0
        self.condense_failures = 0
        self.condense_calls, self.condense_in, self.condense_out = 0, 0, 0  # chars before/after compression

    def take(self):
        if self.calls >= self.cap:
            raise RuntimeError(f"LLM call budget of {self.cap} reached for this hunt")
        self.calls += 1
        limits.count_call()


def _call(model, system, prompt, schema, thinking, images):
    content = prompt
    if images:
        content = [{"type": "text", "text": prompt}] + [
            {"type": "image", "data": b64, "mime_type": mt} for b64, mt in images
        ]
    kwargs = dict(
        model=model,
        input=content,
        response_format={"type": "text", "mime_type": "application/json", "schema": schema},
        generation_config={"thinking_level": thinking},
    )
    if system:
        kwargs["system_instruction"] = system
    r = client().interactions.create(**kwargs)
    return json.loads(r.output_text)


async def ask_json(prompt, schema, *, system=None, budget=None, model=None, thinking="low", images=None):
    """Ask Gemini for JSON matching `schema`. Retries, then falls back to a lighter model."""
    models = [model or config.MODEL, config.FALLBACK_MODEL]
    last = None
    for attempt in range(5):
        m = models[0] if attempt < 3 else models[1]
        try:
            if budget:
                budget.take()
            async with _sem:
                t0 = time.time()
                out = await asyncio.to_thread(_call, m, system, prompt, schema, thinking, images)
                if budget:
                    budget.seconds += time.time() - t0
                return out
        except RuntimeError as e:
            if "budget" in str(e):
                raise
            last = e
        except Exception as e:  # 503 overloaded, bad JSON, network
            last = e
        log.warning("LLM attempt %d on %s failed: %s", attempt + 1, m, last)
        await asyncio.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Gemini failed after retries: {last}")
