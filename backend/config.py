import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

log = logging.getLogger("finsage")

# One place to change model names and limits (they get rotated/retired).
# Groq's free plan enforces an output-tokens-per-minute cap per model, so each
# Groq model gets its own max_tokens. If you see a 429 "OTPM: Limit N", set
# max_tokens at or below N. These models also "think" before answering, and the
# thinking counts toward max_tokens, so reasoning_effort is kept low.
# Every role also has a "fallback" model from the OTHER provider, used if the main one fails.
GROQ_20B = {"provider": "groq", "model": "openai/gpt-oss-20b", "max_tokens": 2048, "reasoning_effort": "low"}
GROQ_120B = {"provider": "groq", "model": "openai/gpt-oss-120b", "max_tokens": 2048, "reasoning_effort": "low"}
GEMINI_LITE = {"provider": "google", "model": "gemini-flash-lite-latest"}

MODELS = {
    "researcher": {**GEMINI_LITE, "fallback": GROQ_120B},
    "analyst": {**GROQ_120B, "fallback": GEMINI_LITE},
    "writer": {**GROQ_20B, "fallback": GEMINI_LITE},
    "verifier": {**GEMINI_LITE, "fallback": GROQ_20B},
}


def get_llm(role: str, temperature: float = 0, max_retries: int = 3, timeout: int = 60,
            use_fallback: bool = False):
    cfg = MODELS[role]["fallback"] if use_fallback else MODELS[role]
    if cfg["provider"] == "google":
        return ChatGoogleGenerativeAI(
            model=cfg["model"],
            google_api_key=os.getenv("GEMINI_API_KEY"),
            temperature=temperature,
            max_retries=max_retries,
            timeout=timeout,
        )
    return ChatGroq(
        model=cfg["model"],
        api_key=os.getenv("GROQ_API_KEY"),
        temperature=temperature,
        max_retries=max_retries,
        timeout=timeout,
        max_tokens=cfg.get("max_tokens", 1000),
        reasoning_effort=cfg.get("reasoning_effort"),
    )


def structured(llm, schema):
    """Structured output; Groq needs the json_schema method, Gemini uses its default."""
    if isinstance(llm, ChatGroq):
        return llm.with_structured_output(schema, method="json_schema")
    return llm.with_structured_output(schema)


async def with_fallback(role: str, call):
    """Run `await call(llm)` with the role's main model; if it fails, try its backup model once."""
    try:
        return await call(get_llm(role))
    except Exception as error:  # noqa: BLE001
        log.warning("%s: main model failed (%s: %s); trying the backup model",
                    role, type(error).__name__, str(error)[:120])
        return await call(get_llm(role, use_fallback=True))