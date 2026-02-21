#!/usr/bin/env python3
"""
LLM integration for Pythia Causal Analysis v2.

Uses Claude CLI (claude --print) which authenticates via Claude Max subscription.
No API key needed.
"""

import json
import logging
import subprocess
import re

logger = logging.getLogger(__name__)


def _claude_call(prompt: str, model: str = "claude-sonnet-4-20250514", max_retries: int = 2) -> str:
    """Call Claude CLI with a prompt. Returns response text."""
    for attempt in range(max_retries + 1):
        try:
            result = subprocess.run(
                ["claude", "--print", "--model", model, prompt],
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
