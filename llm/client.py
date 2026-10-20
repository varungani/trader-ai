"""
TraderAI - LLM client
Primary: Ollama (fully open-source, local).
Optional fallback: Google Gemini if GEMINI_API_KEY is set.
Analyst and Judge MUST use separately configured model names.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from typing import Any, Optional

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    GEMINI_API_KEY,
    GROQ_API_KEY,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    LLM_BACKEND,
    LLM_ANALYST_MODEL,
    LLM_JUDGE_MODEL,
    OLLAMA_BASE_URL,
)

logger = logging.getLogger(__name__)


def llm_available(role: str = "analyst") -> bool:
    backend = _resolve_backend()
    if backend == "ollama":
        return llm_available_force("ollama")
    if backend == "gemini":
        return bool(GEMINI_API_KEY)
    if backend == "groq":
        return bool(GROQ_API_KEY)
    if backend == "openai":
        return bool(OPENAI_API_KEY)
    return False


def llm_available_force(backend: str) -> bool:
    if backend == "ollama":
        try:
            r = requests.get(f"{OLLAMA_BASE_URL.rstrip('/')}/api/tags", timeout=2)
            return r.status_code == 200
        except Exception:
            return False
    return False


def _resolve_backend() -> str:
    backend = (LLM_BACKEND or "auto").lower()
    if backend == "auto":
        if GEMINI_API_KEY:
            return "gemini"
        if GROQ_API_KEY:
            return "groq"
        if OPENAI_API_KEY:
            return "openai"
        if llm_available_force("ollama"):
            return "ollama"
        return "none"
    return backend


def _model_for(role: str) -> str:
    backend = _resolve_backend()
    if backend == "gemini":
        if role == "judge":
            return os.getenv("LLM_JUDGE_MODEL") or "gemini-3.5-flash"
        return os.getenv("LLM_ANALYST_MODEL") or "gemini-3.8-flash"
    if backend == "groq":
        if role == "judge":
            return os.getenv("LLM_JUDGE_MODEL") or "qwen/qwen3.8-27b"
        return os.getenv("LLM_ANALYST_MODEL") or "qwen/qwen3.8-27b"
    if backend == "openai":
        if role == "judge":
            return os.getenv("LLM_JUDGE_MODEL") or "gpt-4o"
        return os.getenv("LLM_ANALYST_MODEL") or "gpt-4o-mini"
    if role == "judge":
        return LLM_JUDGE_MODEL
    return LLM_ANALYST_MODEL


def chat(
    system: str,
    user: str,
    role: str = "analyst",
    temperature: float = 0.2,
    max_tokens: int = 4000,
    json_mode: bool = False,
) -> str:
    """
    Call the LLM for a given role (analyst | judge).
    Roles use different model IDs so the judge is a separate model instance.
    """
    backend = _resolve_backend()
    model = _model_for(role)
    if backend == "ollama":
        return _ollama_chat(model, system, user, temperature, max_tokens)
    if backend == "gemini":
        return _gemini_chat(model, system, user, temperature, max_tokens, json_mode=json_mode)
    if backend == "groq":
        return _openai_chat(
            model, system, user, temperature, max_tokens,
            base_url="https://api.groq.com/openai/v1",
            api_key=GROQ_API_KEY,
            json_mode=json_mode,
        )
    if backend == "openai":
        return _openai_chat(
            model, system, user, temperature, max_tokens,
            base_url=OPENAI_BASE_URL,
            api_key=OPENAI_API_KEY,
            json_mode=json_mode,
        )
    raise RuntimeError(
        "No LLM backend available. Set GEMINI_API_KEY, GROQ_API_KEY, OPENAI_API_KEY in .env, or run Ollama locally."
    )


def chat_json(
    system: str,
    user: str,
    role: str = "analyst",
    temperature: float = 0.1,
    max_tokens: int = 4000,
) -> dict:
    """Force JSON object response; best-effort parse."""
    raw = chat(
        system + "\n\nRespond with a single valid JSON object only. No markdown fences.",
        user,
        role=role,
        temperature=temperature,
        max_tokens=max_tokens,
        json_mode=True,
    )
    return parse_json_loose(raw)


def parse_json_loose(text: str) -> dict:
    if not text:
        return {}
    text = text.strip()
    # Strip ```json fences if present
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try first {...} block
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    logger.warning("Failed to parse LLM JSON; returning raw stub")
    return {"raw": text, "parse_error": True}


def _ollama_chat(model: str, system: str, user: str, temperature: float, max_tokens: int) -> str:
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    resp = requests.post(url, json=payload, timeout=180)
    resp.raise_for_status()
    data = resp.json()
    return (data.get("message") or {}).get("content") or data.get("response") or ""


def _gemini_chat(
    model: str,
    system: str,
    user: str,
    temperature: float,
    max_tokens: int,
    json_mode: bool = False,
) -> str:
    """Optional cloud fallback — not required for OSS path."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY missing")
    model_id = model if model.startswith("gemini") else "gemini-3.8-flash"
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"
        f"?key={GEMINI_API_KEY}"
    )
    gen_config: dict[str, Any] = {
        "temperature": temperature,
        "maxOutputTokens": max_tokens,
    }
    if json_mode:
        gen_config["responseMimeType"] = "application/json"

    payload: dict[str, Any] = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": gen_config,
    }
    try:
        resp = requests.post(url, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            return ""
        parts = ((candidates[0].get("content") or {}).get("parts")) or []
        return "".join(p.get("text", "") for p in parts)
    except requests.exceptions.HTTPError as e:
        status = getattr(e.response, "status_code", None)
        if status in (429, 500, 502, 503, 504) and GROQ_API_KEY:
            logger.warning(f"Gemini {status} error; seamlessly falling back to Groq")
            fallback_model = "qwen/qwen3.8-27b"
            return _openai_chat(
                fallback_model,
                system,
                user,
                temperature,
                max_tokens,
                base_url="https://api.groq.com/openai/v1",
                api_key=GROQ_API_KEY,
                json_mode=json_mode,
            )
        raise


def _openai_chat(
    model: str,
    system: str,
    user: str,
    temperature: float,
    max_tokens: int,
    base_url: str = "",
    api_key: str = "",
    json_mode: bool = False,
) -> str:
    """OpenAI-compatible chat completions (works with Groq, OpenRouter, OpenAI)."""
    if not api_key:
        raise RuntimeError("API key missing for cloud LLM")
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    resp = requests.post(url, headers=headers, json=payload, timeout=90)
    resp.raise_for_status()
    data = resp.json()
    choices = data.get("choices") or []
    if choices:
        return (choices[0].get("message") or {}).get("content", "")
    return ""
