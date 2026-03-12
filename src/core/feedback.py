"""Feedback persistence extracted from causal_v2."""

import json
import logging
import os
from datetime import datetime
from typing import Dict, List

logger = logging.getLogger(__name__)

FEEDBACK_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "causal_feedback.jsonl")


def log_feedback(spike_id: int, feedback_type: str, details: str):
    """
    Log user feedback on attribution quality.

    feedback_type: "correct", "wrong", "partial", "irrelevant"
    details: free text explanation
    """
    entry = {
        "spike_id": spike_id,
        "feedback_type": feedback_type,
        "details": details,
        "timestamp": datetime.utcnow().isoformat(),
    }

    os.makedirs(os.path.dirname(FEEDBACK_FILE), exist_ok=True)
    with open(FEEDBACK_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")

    logger.info("Feedback logged for spike %d: %s", spike_id, feedback_type)


def load_feedback_corrections() -> List[Dict]:
    """Load all feedback for use in improving future prompts."""
    if not os.path.exists(FEEDBACK_FILE):
        return []

    entries = []
    with open(FEEDBACK_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries


def get_feedback_summary() -> str:
    """Summarize feedback patterns for injection into prompts."""
    entries = load_feedback_corrections()
    if not entries:
        return ""

    wrong = [e for e in entries if e["feedback_type"] == "wrong"]

    if not wrong:
        return ""

    corrections = []
    for w in wrong[-5:]:
        corrections.append(f"- Spike #{w['spike_id']}: {w['details']}")

    return (
        "\nIMPORTANT CORRECTIONS FROM PAST MISTAKES:\n"
        + "\n".join(corrections)
        + "\nAvoid repeating these attribution errors.\n"
    )
