#!/usr/bin/env python3
"""
LLM Integration for Pythia — Multi-backend support.

Backends (configured via PYTHIA_LLM_BACKEND env var):
  "openai"   — OpenAI-compatible API (default). Works with:
               Qwen (Alibaba Bailian), DeepSeek, Ollama, vLLM, Together, Groq, OpenRouter
  "claude"   — Claude CLI (claude --print). Requires Claude Max subscription.
  "anthropic"— Direct Anthropic API. Requires ANTHROPIC_API_KEY.

Environment variables:
  PYTHIA_LLM_BACKEND       — "openai" (default), "claude", or "anthropic"
  PYTHIA_LLM_API_KEY       — API key for OpenAI-compatible or Anthropic backend
  PYTHIA_LLM_BASE_URL      — Base URL for OpenAI-compatible API
  PYTHIA_LLM_MODEL         — Model name for fast calls (default: qwen-plus)
  PYTHIA_LLM_MODEL_STRONG  — Model name for deep reasoning (default: same as PYTHIA_LLM_MODEL)
  PYTHIA_LLM_TIMEOUT       — Request timeout in seconds (default: 120)
  PYTHIA_LLM_MAX_RETRIES   — Max retries on failure (default: 2)

Cost comparison (per RCE pipeline run, ~80 LLM calls):
  Qwen-Plus (Alibaba):    ~$0.30-0.50 (recommended for development)
  DeepSeek-V3:            ~$0.20-0.40
  Ollama (local):         $0 (requires GPU, slower)
  Claude Sonnet:          ~$2-4
  GPT-4o:                 ~$3-5
"""

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

# Load .env from project root before reading any env vars
try:
    from dotenv import load_dotenv
    # Walk up from this file to find .env at project root
    _project_root = Path(__file__).resolve().parents[2]
    _env_path = _project_root / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass  # python-dotenv not installed; rely on real env vars

logger = logging.getLogger(__name__)

# Maximum prompt length to prevent runaway costs
MAX_PROMPT_LENGTH = 50_000

# ----------------------------------------------------------------
# Config from environment
# ----------------------------------------------------------------

BACKEND = os.getenv("PYTHIA_LLM_BACKEND", "openai").lower()
API_KEY = os.getenv("PYTHIA_LLM_API_KEY", "")
BASE_URL = os.getenv("PYTHIA_LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
MODEL_FAST = os.getenv("PYTHIA_LLM_MODEL", "qwen-plus")
MODEL_STRONG = os.getenv("PYTHIA_LLM_MODEL_STRONG", "") or MODEL_FAST
TIMEOUT = int(os.getenv("PYTHIA_LLM_TIMEOUT", "120"))
MAX_RETRIES = int(os.getenv("PYTHIA_LLM_MAX_RETRIES", "2"))


# ----------------------------------------------------------------
# Input sanitization
# ----------------------------------------------------------------

def sanitize_llm_input(text: str) -> str:
    """
    Sanitize text before passing to LLM calls.
    Strips control characters and truncates to max length.
    """
    if not isinstance(text, str):
        text = str(text)

    # Strip null bytes and control characters (except newline/tab)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)

    # Truncate to max length
    if len(text) > MAX_PROMPT_LENGTH:
        text = text[:MAX_PROMPT_LENGTH] + "\n[truncated]"
        logger.warning("Prompt truncated to %d chars", MAX_PROMPT_LENGTH)

    return text


# ----------------------------------------------------------------
# Backend: OpenAI-compatible API
# Works with: Qwen, DeepSeek, Ollama, vLLM, Together, Groq, OpenRouter, OpenAI
# ----------------------------------------------------------------

# Lazy-loaded client
_openai_client = None


def _get_openai_client():
    """Get or create OpenAI-compatible client."""
    global _openai_client
    if _openai_client is not None:
        return _openai_client

    try:
        from openai import OpenAI
    except ImportError:
        logger.error(
            "openai package not installed. Run: pip install openai --break-system-packages"
        )
        return None

    if not API_KEY:
        logger.error(
            "PYTHIA_LLM_API_KEY not set. Get a key from your LLM provider:\n"
            "  Qwen (Alibaba Bailian): https://bailian.console.aliyun.com/\n"
            "  DeepSeek: https://platform.deepseek.com/\n"
            "  OpenRouter: https://openrouter.ai/keys\n"
            "  Ollama (local): set PYTHIA_LLM_API_KEY=ollama PYTHIA_LLM_BASE_URL=http://localhost:11434/v1"
        )
        return None

    _openai_client = OpenAI(
        api_key=API_KEY,
        base_url=BASE_URL,
        timeout=TIMEOUT,
    )

    logger.info("OpenAI-compatible client initialized: base_url=%s, model=%s", BASE_URL, MODEL_FAST)
    return _openai_client


def _openai_call(prompt: str, model: str = None, temperature: float = 0.3) -> str:
    """Call OpenAI-compatible API."""
    prompt = sanitize_llm_input(prompt)
    model = model or MODEL_FAST
    client = _get_openai_client()

    if client is None:
        return ""

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=4096,
            )
            content = response.choices[0].message.content
            return (content or "").strip()

        except Exception as e:
            logger.warning("OpenAI API error (attempt %d/%d): %s", attempt + 1, MAX_RETRIES + 1, e)
            if attempt < MAX_RETRIES:
                import time
                time.sleep(2 ** attempt)  # Exponential backoff

    return ""


# ----------------------------------------------------------------
# Backend: Claude CLI
# ----------------------------------------------------------------

def _claude_call(prompt: str, model: str = "claude-sonnet-4-20250514") -> str:
    """Call Claude CLI with a prompt."""
    prompt = sanitize_llm_input(prompt)

    for attempt in range(MAX_RETRIES + 1):
        try:
            result = subprocess.run(
                ["claude", "--print", "--model", model, "-p", prompt],
                capture_output=True, text=True, timeout=TIMEOUT,
            )
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                logger.warning("Claude CLI error (attempt %d): %s", attempt, result.stderr[:200])
        except subprocess.TimeoutExpired:
            logger.warning("Claude CLI timeout (attempt %d)", attempt)
        except FileNotFoundError:
            logger.error("Claude CLI not found. Install: npm install -g @anthropic-ai/claude-cli")
            return ""
        except Exception as e:
            logger.warning("Claude CLI failed (attempt %d): %s", attempt, e)

    return ""


# ----------------------------------------------------------------
# Backend: Direct Anthropic API
# ----------------------------------------------------------------

_anthropic_client = None


def _get_anthropic_client():
    """Get or create Anthropic API client."""
    global _anthropic_client
    if _anthropic_client is not None:
        return _anthropic_client

    try:
        import anthropic
    except ImportError:
        logger.error("anthropic package not installed. Run: pip install anthropic --break-system-packages")
        return None

    key = API_KEY or os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        logger.error("PYTHIA_LLM_API_KEY or ANTHROPIC_API_KEY not set")
        return None

    _anthropic_client = anthropic.Anthropic(api_key=key)
    logger.info("Anthropic client initialized")
    return _anthropic_client


def _anthropic_call(prompt: str, model: str = "claude-sonnet-4-20250514") -> str:
    """Call Anthropic API directly."""
    prompt = sanitize_llm_input(prompt)
    client = _get_anthropic_client()

    if client is None:
        return ""

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()

        except Exception as e:
            logger.warning("Anthropic API error (attempt %d): %s", attempt, e)
            if attempt < MAX_RETRIES:
                import time
                time.sleep(2 ** attempt)

    return ""


# ----------------------------------------------------------------
# Unified interface — routes to configured backend
# ----------------------------------------------------------------

def _dispatch(prompt: str, model: str = None, strong: bool = False) -> str:
    """Route LLM call to the configured backend."""
    if BACKEND == "claude":
        claude_model = "claude-opus-4-20250514" if strong else "claude-sonnet-4-20250514"
        return _claude_call(prompt, model=model or claude_model)

    elif BACKEND == "anthropic":
        anthropic_model = "claude-opus-4-20250514" if strong else "claude-sonnet-4-20250514"
        return _anthropic_call(prompt, model=model or anthropic_model)

    else:  # "openai" — default
        openai_model = MODEL_STRONG if strong else MODEL_FAST
        return _openai_call(prompt, model=model or openai_model)


# ----------------------------------------------------------------
# Public API — drop-in replacements for existing code
# ----------------------------------------------------------------

def sonnet_call(prompt: str) -> str:
    """Fast model call (filtering, proposals, critiques).

    Maps to:
      openai backend  → PYTHIA_LLM_MODEL (default: qwen-plus)
      claude backend  → claude-sonnet-4-20250514
      anthropic       → claude-sonnet-4-20250514
    """
    return _dispatch(prompt, strong=False)


def opus_call(prompt: str) -> str:
    """Strong model call (ontology extraction, deep reasoning).

    Maps to:
      openai backend  → PYTHIA_LLM_MODEL_STRONG (default: same as fast)
      claude backend  → claude-opus-4-20250514
      anthropic       → claude-opus-4-20250514
    """
    return _dispatch(prompt, strong=True)


def llm_call(prompt: str, model: str = None) -> str:
    """Generic LLM call with optional model override."""
    return _dispatch(prompt, model=model)


# ----------------------------------------------------------------
# Provider presets — convenience configs
# ----------------------------------------------------------------

PROVIDER_PRESETS = {
    "qwen": {
        "PYTHIA_LLM_BACKEND": "openai",
        "PYTHIA_LLM_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "PYTHIA_LLM_MODEL": "qwen-plus",
        "PYTHIA_LLM_MODEL_STRONG": "qwen-max",
    },
    "deepseek": {
        "PYTHIA_LLM_BACKEND": "openai",
        "PYTHIA_LLM_BASE_URL": "https://api.deepseek.com",
        "PYTHIA_LLM_MODEL": "deepseek-chat",
        "PYTHIA_LLM_MODEL_STRONG": "deepseek-reasoner",
    },
    "ollama": {
        "PYTHIA_LLM_BACKEND": "openai",
        "PYTHIA_LLM_BASE_URL": "http://localhost:11434/v1",
        "PYTHIA_LLM_API_KEY": "ollama",
        "PYTHIA_LLM_MODEL": "qwen2.5:14b",
        "PYTHIA_LLM_MODEL_STRONG": "qwen2.5:72b",
    },
    "openrouter": {
        "PYTHIA_LLM_BACKEND": "openai",
        "PYTHIA_LLM_BASE_URL": "https://openrouter.ai/api/v1",
        "PYTHIA_LLM_MODEL": "qwen/qwen-2.5-72b-instruct",
        "PYTHIA_LLM_MODEL_STRONG": "qwen/qwen-2.5-72b-instruct",
    },
    "claude": {
        "PYTHIA_LLM_BACKEND": "claude",
    },
    "anthropic": {
        "PYTHIA_LLM_BACKEND": "anthropic",
    },
}


def print_config():
    """Print current LLM configuration (for debugging)."""
    print(f"Backend:      {BACKEND}")
    print(f"Base URL:     {BASE_URL}")
    print(f"Fast model:   {MODEL_FAST}")
    print(f"Strong model: {MODEL_STRONG}")
    print(f"API key:      {'***' + API_KEY[-4:] if len(API_KEY) > 4 else '(not set)'}")
    print(f"Timeout:      {TIMEOUT}s")
    print(f"Max retries:  {MAX_RETRIES}")


if __name__ == "__main__":
    print_config()
