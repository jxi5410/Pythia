"""Market classification and entity extraction utilities extracted from causal_v2."""

import json
import logging
import re
from typing import Dict, List

logger = logging.getLogger(__name__)

CATEGORY_KEYWORDS = {
    "fed_rate": ["fed", "federal reserve", "fomc", "interest rate", "powell", "rate cut", "rate hike", "monetary policy"],
    "inflation": ["inflation", "cpi", "pce", "consumer price", "deflation"],
    "election": ["election", "president", "vote", "candidate", "ballot", "republican", "democrat", "trump", "biden"],
    "crypto": ["bitcoin", "btc", "ethereum", "eth", "crypto", "blockchain", "defi", "token"],
    "trade_war": ["tariff", "trade war", "sanctions", "import duty", "trade deal", "embargo"],
    "geopolitical": ["war", "ceasefire", "nato", "invasion", "military", "peace deal", "nuclear"],
    "tech": ["openai", "gpt", "google", "apple", "ai regulation", "antitrust", "tiktok"],
    "recession": ["recession", "gdp", "unemployment", "yield curve", "layoffs", "economic growth"],
    "energy": ["oil", "opec", "natural gas", "energy", "petroleum", "barrel"],
}


def classify_market(title: str) -> str:
    """Classify a market into a category based on title keywords."""
    title_lower = title.lower()
    scores = {}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in title_lower)
        if score > 0:
            scores[cat] = score
    return max(scores, key=scores.get) if scores else "general"


def extract_entities_simple(title: str) -> List[str]:
    """Extract key entities from market title without LLM (fast fallback)."""
    stop_words = {"will", "the", "be", "in", "by", "of", "a", "an", "to", "for", "on", "is", "at", "this", "that", "it"}
    words = re.sub(r'[?!.,]', '', title).split()
    entities = [w for w in words if w.lower() not in stop_words and len(w) > 2]
    return entities[:5]


ENTITY_PROMPT = """Extract the key searchable entities from this prediction market title.
Return ONLY a JSON array of 3-5 specific search terms that would find news causing price moves in this market.

Title: {title}

Examples:
- "Will the Fed cut rates by June 2025?" → ["Federal Reserve rate cut", "FOMC June 2025", "Jerome Powell dovish"]
- "Bitcoin above 100K by June?" → ["Bitcoin price 100000", "BTC rally", "crypto market surge"]

Return ONLY the JSON array, nothing else."""


def extract_entities_llm(title: str, llm_call=None) -> List[str]:
    """Extract entities using LLM for better search queries."""
    if not llm_call:
        return extract_entities_simple(title)

    try:
        response = llm_call(ENTITY_PROMPT.format(title=title))
        match = re.search(r'\[.*\]', response, re.DOTALL)
        if match:
            entities = json.loads(match.group())
            if isinstance(entities, list) and entities:
                return [str(e) for e in entities[:5]]
    except Exception as e:
        logger.warning("LLM entity extraction failed: %s", e)

    return extract_entities_simple(title)
