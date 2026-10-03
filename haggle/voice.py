"""Voice input: the user speaks their request, Gemini 3.5 Transcribe turns it into text.

The browser records a short clip (webm/opus or mp4/aac) and posts the raw bytes here. Language is
auto-detected (Swedish or English); a custom vocabulary keeps hardware names and Swedish places right.
"""
import asyncio
import base64

from .llm import client

MODEL = "gemini-3.5-transcribe"
VOCAB = ["RTX 3060", "RTX 3060 Ti", "RTX 3070", "RTX 4060", "RX 6700 XT", "GeForce", "Radeon", "SSD", "NVMe",
         "16 GB", "1 TB", "SEK", "kronor", "Blocket", "Tradera", "Facebook Marketplace", "speldator", "gaming PC",
         "Stockholm", "Solna", "Södermalm", "Kungsholmen", "Nacka", "Huddinge", "Sundbyberg", "Täby"]


def _transcribe(data: bytes, mime: str) -> str:
    mime = (mime or "audio/webm").split(";")[0]
    r = client().interactions.create(
        model=MODEL,
        input=[{"type": "audio", "data": base64.b64encode(data).decode(), "mime_type": mime}],
        generation_config={"transcription_config": {"language_codes": [], "custom_vocabulary": VOCAB}},
    )
    return (r.output_text or "").strip()


async def transcribe(data: bytes, mime: str) -> str:
    return await asyncio.to_thread(_transcribe, data, mime)
