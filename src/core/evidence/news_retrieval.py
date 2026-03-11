import logging
import os
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional
from urllib.parse import quote_plus, unquote, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "")

SUBREDDIT_MAP = {
    "fed_rate": "economics+finance+investing",
    "inflation": "economics+finance",
    "election": "politics+news",
    "crypto": "cryptocurrency+bitcoin+ethtrader",
    "trade_war": "economics+worldnews",
    "geopolitical": "worldnews+geopolitics",
    "tech": "technology+artificial",
    "recession": "economics+finance",
    "energy": "energy+oil",
    "general": "news",
}


def newsapi_search(query: str, from_date: str = None, to_date: str = None, max_results: int = 10) -> List[Dict]:
    if not NEWSAPI_KEY:
        return []
    try:
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": query,
            "apiKey": NEWSAPI_KEY,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": max_results,
        }
        if from_date:
            params["from"] = from_date[:19]
        if to_date:
            params["to"] = to_date[:19]

        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        articles = []
        for art in data.get("articles", []):
            articles.append({
                "headline": (art.get("title") or "")[:200],
                "url": art.get("url", ""),
                "source": art.get("source", {}).get("name", ""),
                "snippet": (art.get("description") or "")[:200],
                "published": art.get("publishedAt", ""),
                "retrieval_source": "newsapi",
            })
        return articles
    except Exception as e:
        logger.warning("NewsAPI search failed: %s", e)
        return []


def _parse_published_date(date_str: str) -> Optional[datetime]:
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        pass
    try:
        return parsedate_to_datetime(date_str).replace(tzinfo=None)
    except Exception:
        pass
    return None


def filter_by_temporal_window(articles: List[Dict], window_start: str, window_end: str) -> List[Dict]:
    try:
        ws = datetime.fromisoformat(window_start)
        we = datetime.fromisoformat(window_end)
    except Exception:
        return articles

    filtered = []
    for art in articles:
        pub_date = _parse_published_date(art.get("published", ""))
        if pub_date is None:
            art["temporal_verified"] = False
            filtered.append(art)
        elif ws <= pub_date <= we:
            art["temporal_verified"] = True
            filtered.append(art)
    return filtered


def google_news_rss(query: str, max_results: int = 10) -> List[Dict]:
    try:
        url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0 (compatible; PythiaLive/2.0)"})
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "xml")
        articles = []
        for item in soup.find_all("item")[:max_results]:
            title = item.find("title")
            link = item.find("link")
            pub_date = item.find("pubDate")
            source = item.find("source")
            articles.append({
                "headline": title.get_text(strip=True) if title else "",
                "url": link.get_text(strip=True) if link else "",
                "source": source.get_text(strip=True) if source else "",
                "published": pub_date.get_text(strip=True) if pub_date else "",
                "retrieval_source": "google_news_rss",
            })
        return articles
    except Exception as e:
        logger.warning("Google News RSS failed: %s", e)
        return []


def duckduckgo_search(query: str, max_results: int = 5) -> List[Dict]:
    try:
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        resp = requests.get(url, timeout=5, headers={"User-Agent": "Mozilla/5.0 (compatible; PythiaLive/2.0)"})
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        articles = []
        for result in soup.select(".result__body")[:max_results]:
            title_el = result.select_one(".result__a")
            snippet_el = result.select_one(".result__snippet")
            if not title_el:
                continue
            headline = title_el.get_text(strip=True)
            link = title_el.get("href", "")

            if "/l/?uddg=" in link:
                match = re.search(r"uddg=([^&]+)", link)
                if match:
                    link = unquote(match.group(1))

            domain = ""
            try:
                domain = urlparse(link).netloc.replace("www.", "")
            except Exception:
                pass

            articles.append({
                "headline": headline[:200],
                "url": link,
                "source": domain,
                "snippet": snippet_el.get_text(strip=True)[:200] if snippet_el else "",
                "retrieval_source": "duckduckgo",
            })
        return articles
    except Exception as e:
        logger.warning("DuckDuckGo search failed: %s", e)
        return []


def reddit_search(query: str, subreddit: str = "news", max_results: int = 5) -> List[Dict]:
    try:
        url = f"https://www.reddit.com/r/{subreddit}/search.json"
        params = {
            "q": query,
            "sort": "new",
            "limit": max_results,
            "restrict_sr": "true",
            "t": "day",
        }
        resp = requests.get(url, params=params, timeout=10, headers={"User-Agent": "PythiaLive/2.0"})
        resp.raise_for_status()

        data = resp.json()
        articles = []
        for post in data.get("data", {}).get("children", []):
            d = post.get("data", {})
            articles.append({
                "headline": d.get("title", "")[:200],
                "url": f"https://reddit.com{d.get('permalink', '')}",
                "source": f"r/{subreddit}",
                "snippet": d.get("selftext", "")[:200],
                "score": d.get("score", 0),
                "retrieval_source": "reddit",
            })
        return articles
    except Exception as e:
        logger.warning("Reddit search failed: %s", e)
        return []


def retrieve_candidate_news(context: Dict) -> List[Dict]:
    entities = context["entities"]
    category = context["category"]
    window = context["temporal_window"]

    entity_query = " ".join(entities[:3])
    category_query = f"{entity_query} {category.replace('_', ' ')}"

    candidates = []
    candidates += newsapi_search(entity_query, from_date=window["start"], to_date=window["end"], max_results=10)
    candidates += google_news_rss(entity_query, max_results=8)
    candidates += duckduckgo_search(category_query, max_results=5)

    subreddit = SUBREDDIT_MAP.get(category, "news")
    candidates += reddit_search(entity_query, subreddit=subreddit, max_results=5)

    candidates = filter_by_temporal_window(candidates, window["start"], window["end"])

    seen_headlines = set()
    unique = []
    for article in candidates:
        headline_key = article["headline"][:50].lower()
        if headline_key not in seen_headlines:
            seen_headlines.add(headline_key)
            unique.append(article)
    return unique
