"""
News Context
Lightweight news search using DuckDuckGo Instant Answer API.
"""
import requests
from typing import List, Dict


def get_news_context(market_title: str, max_results: int = 3) -> List[Dict]:
    """
    Search for recent news related to the market event.

    Uses DuckDuckGo Instant Answer API (free, no key needed).
    Returns [{title, url, snippet}].
    Fallback: returns empty list if API fails (non-critical).
    """
    try:
        # Clean up the title into a search query
        query = market_title.strip("?").strip()

        resp = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []

        # Extract from RelatedTopics
        for topic in data.get("RelatedTopics", []):
            if "Text" in topic and "FirstURL" in topic:
                results.append({
                    "title": topic["Text"][:120],
                    "url": topic["FirstURL"],
                    "snippet": topic.get("Text", "")[:200],
                })
            # Handle subtopics (grouped topics)
            elif "Topics" in topic:
                for sub in topic["Topics"]:
                    if "Text" in sub and "FirstURL" in sub:
                        results.append({
                            "title": sub["Text"][:120],
                            "url": sub["FirstURL"],
                            "snippet": sub.get("Text", "")[:200],
                        })
            if len(results) >= max_results:
                break

        # Also check AbstractText
        abstract = data.get("AbstractText", "")
        abstract_url = data.get("AbstractURL", "")
        if abstract and abstract_url and len(results) < max_results:
            results.insert(0, {
                "title": data.get("Heading", "Context"),
                "url": abstract_url,
                "snippet": abstract[:200],
            })

        return results[:max_results]

    except Exception:
        return []
