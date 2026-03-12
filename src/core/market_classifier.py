"""Market classification and entity extraction utilities extracted from causal_v2."""

import json
import logging
import re
from typing import Dict, List

logger = logging.getLogger(__name__)

CATEGORY_KEYWORDS = {
    "fed_rate": ["fed", "federal reserve", "fomc", "interest rate", "powell", "rate cut", "rate hike", "monetary policy", "basis points", "bps", "dovish", "hawkish", "tightening", "easing"],
    "inflation": ["inflation", "cpi", "pce", "consumer price", "deflation", "stagflation", "price index", "core inflation"],
    "election": ["election", "president", "vote", "candidate", "ballot", "republican", "democrat", "trump", "biden", "harris", "desantis", "nomination", "primary", "electoral", "governor", "senate", "congress", "midterm", "inauguration"],
    "crypto": ["bitcoin", "btc", "ethereum", "eth", "crypto", "blockchain", "defi", "token", "solana", "sol", "dogecoin", "memecoin", "nft", "stablecoin", "binance", "coinbase", "halving"],
    "trade_war": ["tariff", "trade war", "sanctions", "import duty", "trade deal", "embargo", "export control", "trade deficit", "dumping", "wto", "trade policy", "customs"],
    "geopolitical": ["war", "ceasefire", "nato", "invasion", "military", "peace deal", "nuclear", "iran", "israel", "ukraine", "russia", "china", "taiwan", "strait", "hormuz", "gaza", "hamas", "hezbollah", "missile", "drone", "troops", "conflict", "escalation", "de-escalation", "diplomacy", "treaty", "annex", "occupation", "territorial", "sovereignty", "regime", "coup", "assassination", "hostage", "refugee", "humanitarian", "un security council", "sanctions", "blockade", "naval", "airspace", "no-fly zone"],
    "tech": ["openai", "gpt", "google", "apple", "ai regulation", "antitrust", "tiktok", "meta", "microsoft", "nvidia", "semiconductor", "chip", "ai safety", "deepfake", "autonomous", "spacex", "tesla"],
    "recession": ["recession", "gdp", "unemployment", "yield curve", "layoffs", "economic growth", "jobs report", "nonfarm", "payroll", "consumer confidence", "pmi", "manufacturing", "contraction"],
    "energy": ["oil", "opec", "natural gas", "energy", "petroleum", "barrel", "crude", "lng", "pipeline", "refinery", "saudi", "aramco", "shale", "renewables", "solar", "nuclear energy"],
    "climate": ["climate", "carbon", "emissions", "paris agreement", "cop", "net zero", "green deal", "wildfire", "hurricane", "flood", "drought", "weather"],
    "health": ["pandemic", "vaccine", "covid", "who", "fda", "drug approval", "pharma", "outbreak", "epidemic", "bird flu", "h5n1"],
    "sports": ["nba", "nfl", "premier league", "champions league", "world cup", "olympics", "fifa", "super bowl", "playoff", "championship", "mvp", "transfer"],
    "entertainment": ["oscar", "grammy", "emmy", "box office", "streaming", "netflix", "disney", "album", "concert", "gta"],
}


def classify_market(title: str, llm_call=None) -> str:
    """Classify a market into a category. Uses LLM if available, else keywords."""
    # Try LLM first for accurate classification
    if llm_call:
        try:
            categories = list(CATEGORY_KEYWORDS.keys())
            prompt = f"""Classify this prediction market into exactly ONE category.

Market: "{title}"

Categories: {', '.join(categories)}

Reply with ONLY the category name, nothing else. If none fit well, reply "general"."""
            response = llm_call(prompt).strip().lower().replace('"', '').replace("'", "")
            # Find the best match
            for cat in categories:
                if cat in response:
                    return cat
            if "general" in response:
                return "general"
        except Exception as e:
            logger.debug("LLM classification failed, using keywords: %s", e)

    # Fallback: keyword matching
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
