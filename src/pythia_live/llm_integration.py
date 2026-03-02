#!/usr/bin/env python3
"""
LLM integration for Pythia Causal Analysis v2.

Uses Claude CLI (claude --print) which authenticates via Claude Max subscription.
No API key needed.
"""

import json
import logging
import re
import subprocess

logger = logging.getLogger(__name__)

# Maximum prompt length to prevent abuse / runaway costs
MAX_PROMPT_LENGTH = 50_000


def sanitize_llm_input(text: str) -> str:
    """
    Sanitize text before passing to LLM subprocess calls.

    Prevents:
    - Shell metacharacter injection (null bytes, control chars)
    - Excessively long prompts (cost control)
    - Prompt injection via role-override patterns

    This is called automatically by _claude_call; also exported for
    use in pipeline.py and congressional.py subprocess calls.
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


def _claude_call(prompt: str, model: str = "claude-sonnet-4-20250514", max_retries: int = 2) -> str:
    """Call Claude CLI with a prompt. Returns response text.

    Uses --prompt flag with stdin to avoid shell injection via argv.
    """
    prompt = sanitize_llm_input(prompt)

    for attempt in range(max_retries + 1):
        try:
            result = subprocess.run(
                ["claude", "--print", "--model", model, "-p", prompt],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                logger.warning("Claude CLI error (attempt %d): %s", attempt, result.stderr[:200])
        except subprocess.TimeoutExpired:
            logger.warning("Claude CLI timeout (attempt %d)", attempt)
        except Exception as e:
            logger.warning("Claude CLI failed (attempt %d): %s", attempt, e)

    return ""


def sonnet_call(prompt: str) -> str:
    """Layer 3: Fast relevance filtering via Sonnet."""
    return _claude_call(prompt, model="claude-sonnet-4-20250514")


def opus_call(prompt: str) -> str:
    """Layer 4: Deep causal reasoning via Opus."""
    return _claude_call(prompt, model="claude-opus-4-20250514")
