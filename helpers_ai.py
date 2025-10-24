from openai import OpenAI
import os, json, hashlib
from datetime import datetime, timedelta

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

_cache = {}
CACHE_TTL_MINUTES = 30

def _cache_key(widget: str, data: dict):
    raw = json.dumps(data, sort_keys=True)
    return hashlib.md5(f"{widget}:{raw}".encode()).hexdigest()

def summarize_widget(widget: str, data: dict) -> str:
    key = _cache_key(widget, data)
    if key in _cache and datetime.now() - _cache[key]["time"] < timedelta(minutes=CACHE_TTL_MINUTES):
        return _cache[key]["summary"]

    serialized = json.dumps(data)[:4000]

    instructions = (
        "You are an analytics assistant for a retail store. "
        "Write a one-sentence, human-friendly summary (max 50 words) "
        "of the data. Mention major trends or anomalies."
    )

    try:
        response = client.responses.create(
            model="gpt-5",
            instructions=instructions,
            input=serialized,
            max_output_tokens=2000
        )
        summary = response.output_text.strip()
    except Exception as e:
        summary = f"(AI summary unavailable: {e})"

    _cache[key] = {"summary": summary, "time": datetime.now()}
    return summary
