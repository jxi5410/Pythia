"""
Correlation Engine
Finds related markets when a signal fires.
"""
import re
import sqlite3
from typing import List, Dict

from .database import PythiaDB
from .cross_correlation import CrossCorrelationEngine


# Words too common to be useful for matching
_STOP_WORDS = frozenset({
    "the", "a", "an", "in", "on", "at", "to", "of", "for", "is", "it",
    "and", "or", "by", "be", "will", "what", "who", "how", "when", "where",
    "this", "that", "with", "from", "are", "was", "has", "have", "do", "does",
    "not", "no", "yes", "before", "after", "above", "below", "between",
    "than", "more", "less", "over", "under",
})


def _extract_keywords(text: str) -> set:
    """Extract meaningful keywords from a market title."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if len(w) > 2 and w not in _STOP_WORDS}


def find_correlated_markets(
    db: PythiaDB,
    market_id: str,
    market_title: str,
    limit: int = 5,
    use_statistical: bool = True,
) -> List[Dict]:
    """
    Find markets related to the signal market.

    Uses keyword overlap from market titles + same category.
    Returns list of {title, yes_price, price_change_1h, relevance_score}.
    """
    if use_statistical:
        try:
            engine = CrossCorrelationEngine(db)
            statistical = engine.find_statistically_correlated(market_id)
            if statistical:
                out = []
                for row in statistical[:limit]:
                    market = db.get_market(row["market_id"]) or {}
                    out.append({
                        "market_id": row["market_id"],
                        "title": market.get("title", row["market_id"]),
                        "yes_price": None,
                        "price_change_1h": None,
                        "relevance_score": round(abs(row.get("rho", 0.0)), 3),
                        "p_value": row.get("p_value"),
                        "method": "spearman",
                    })
                return out
        except Exception:
            pass

    keywords = _extract_keywords(market_title)
    if not keywords:
        return []

    try:
        with sqlite3.connect(db.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Get all other active markets
            rows = conn.execute("""
                SELECT m.id, m.title, m.category,
                       p_latest.yes_price,
                       p_old.yes_price AS old_yes_price
                FROM markets m
                LEFT JOIN (
                    SELECT market_id, yes_price,
                           ROW_NUMBER() OVER (PARTITION BY market_id ORDER BY timestamp DESC) AS rn
                    FROM prices
                ) p_latest ON p_latest.market_id = m.id AND p_latest.rn = 1
                LEFT JOIN (
                    SELECT market_id, yes_price,
                           ROW_NUMBER() OVER (
                               PARTITION BY market_id
                               ORDER BY ABS(
                                   julianday(timestamp) - julianday('now', '-1 hour')
                               )
                           ) AS rn
                    FROM prices
                    WHERE timestamp > datetime('now', '-2 hours')
                ) p_old ON p_old.market_id = m.id AND p_old.rn = 1
                WHERE m.id != ?
                ORDER BY m.liquidity DESC
                LIMIT 500
            """, (market_id,)).fetchall()

            scored = []
            for row in rows:
                other_keywords = _extract_keywords(row["title"] or "")
                overlap = keywords & other_keywords
                if not overlap:
                    continue

                relevance = len(overlap) / max(len(keywords), 1)
                yes_price = row["yes_price"] or 0.0
                old_price = row["old_yes_price"]
                change = (yes_price - old_price) if old_price is not None else None

                scored.append({
                    "title": row["title"],
                    "yes_price": round(yes_price, 4),
                    "price_change_1h": round(change, 4) if change is not None else None,
                    "relevance_score": round(relevance, 3),
                })

            # Sort by relevance then by absolute price change
            scored.sort(
                key=lambda x: (
                    x["relevance_score"],
                    abs(x["price_change_1h"]) if x["price_change_1h"] is not None else 0,
                ),
                reverse=True,
            )
            return scored[:limit]

    except Exception:
        return []
