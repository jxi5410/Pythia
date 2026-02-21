#!/usr/bin/env python3
"""
Pythia Congressional Trading Module — Track congressional stock trades and
cross-reference with prediction market contracts.

Data sources (all free):
- Quiver Quant API (free tier)
- Capitol Trades (scraping fallback)
- Hardcoded politician profiles from public records
"""

import json
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

CACHE_DIR = Path(__file__).parent.parent.parent / ".cache" / "congressional"
CACHE_TTL = 3600  # 1 hour


def _cache_path(key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{key}.json"


def _cache_get(key: str) -> Optional[list]:
    p = _cache_path(key)
    if p.exists():
        data = json.loads(p.read_text())
        if time.time() - data.get("ts", 0) < CACHE_TTL:
            return data["payload"]
    return None


def _cache_set(key: str, payload):
    p = _cache_path(key)
    p.write_text(json.dumps({"ts": time.time(), "payload": payload}))


# ---------------------------------------------------------------------------
# Politician Profiles (top 20 most active traders)
# ---------------------------------------------------------------------------

POLITICIAN_PROFILES: Dict[str, dict] = {
    "Nancy Pelosi": {
        "party": "D", "chamber": "House", "state": "CA-11",
        "committees": ["Select Committee on the Climate Crisis (former)"],
        "known_sectors": ["Tech", "Semiconductors", "AI"],
        "notable": "Former Speaker. Husband Paul Pelosi executes trades.",
    },
    "Tommy Tuberville": {
        "party": "R", "chamber": "Senate", "state": "AL",
        "committees": ["Armed Services", "Agriculture", "Veterans' Affairs"],
        "known_sectors": ["Defense", "Agriculture", "Finance"],
        "notable": "Hundreds of trades, many late disclosures. STOCK Act scrutiny.",
    },
    "Dan Crenshaw": {
        "party": "R", "chamber": "House", "state": "TX-2",
        "committees": ["Energy and Commerce", "Intelligence"],
        "known_sectors": ["Energy", "Tech", "Defense"],
        "notable": "Active options trader.",
    },
    "Mark Green": {
        "party": "R", "chamber": "House", "state": "TN-7",
        "committees": ["Homeland Security (Chair)", "Armed Services"],
        "known_sectors": ["Defense", "Healthcare"],
        "notable": "Chair of Homeland Security Committee.",
    },
    "Josh Gottheimer": {
        "party": "D", "chamber": "House", "state": "NJ-5",
        "committees": ["Financial Services"],
        "known_sectors": ["Finance", "Tech"],
        "notable": "One of the most active House traders.",
    },
    "Michael McCaul": {
        "party": "R", "chamber": "House", "state": "TX-10",
        "committees": ["Foreign Affairs (Chair)", "Homeland Security"],
        "known_sectors": ["Defense", "Tech", "Semiconductors"],
        "notable": "Wealthiest member of Congress.",
    },
    "Ro Khanna": {
        "party": "D", "chamber": "House", "state": "CA-17",
        "committees": ["Armed Services", "Oversight"],
        "known_sectors": ["Tech", "Defense"],
        "notable": "Silicon Valley representative.",
    },
    "John Curtis": {
        "party": "R", "chamber": "Senate", "state": "UT",
        "committees": ["Energy and Natural Resources"],
        "known_sectors": ["Energy", "Tech"],
        "notable": "Elected to Senate 2024.",
    },
    "Pete Sessions": {
        "party": "R", "chamber": "House", "state": "TX-17",
        "committees": ["Financial Services"],
        "known_sectors": ["Finance", "Tech"],
        "notable": "Active in financial sector trades.",
    },
    "Shelley Moore Capito": {
        "party": "R", "chamber": "Senate", "state": "WV",
        "committees": ["Appropriations", "Commerce", "Environment"],
        "known_sectors": ["Energy", "Infrastructure"],
        "notable": "Appropriations committee member.",
    },
    "Gary Palmer": {
        "party": "R", "chamber": "House", "state": "AL-6",
        "committees": ["Energy and Commerce", "Oversight"],
        "known_sectors": ["Energy", "Healthcare"],
        "notable": "Frequent trader in energy stocks.",
    },
    "Pat Fallon": {
        "party": "R", "chamber": "House", "state": "TX-4",
        "committees": ["Armed Services", "Oversight"],
        "known_sectors": ["Defense", "Tech"],
        "notable": "Very active trader, hundreds of transactions.",
    },
    "John Hickenlooper": {
        "party": "D", "chamber": "Senate", "state": "CO",
        "committees": ["Commerce", "Energy", "Health"],
        "known_sectors": ["Energy", "Tech", "Healthcare"],
        "notable": "Former governor, active in energy trades.",
    },
    "Kevin Hern": {
        "party": "R", "chamber": "House", "state": "OK-1",
        "committees": ["Ways and Means", "Budget"],
        "known_sectors": ["Energy", "Finance"],
        "notable": "McDonald's franchise owner, active trader.",
    },
    "Markwayne Mullin": {
        "party": "R", "chamber": "Senate", "state": "OK",
        "committees": ["Armed Services", "Environment", "Indian Affairs"],
        "known_sectors": ["Energy", "Defense"],
        "notable": "Business owner with active portfolio.",
    },
    "Kurt Schrader": {
        "party": "D", "chamber": "House", "state": "OR-5",
        "committees": ["Energy and Commerce"],
        "known_sectors": ["Healthcare", "Pharma"],
        "notable": "Veterinarian, active pharma trader. Lost 2022 primary.",
    },
    "Virginia Foxx": {
        "party": "R", "chamber": "House", "state": "NC-5",
        "committees": ["Education and Workforce (Chair)"],
        "known_sectors": ["Education", "Finance"],
        "notable": "Chair of Education committee.",
    },
    "Marie Gluesenkamp Perez": {
        "party": "D", "chamber": "House", "state": "WA-3",
        "committees": ["Small Business", "Agriculture"],
        "known_sectors": ["Manufacturing", "Agriculture"],
        "notable": "Swing district, active trader.",
    },
    "David Rouzer": {
        "party": "R", "chamber": "House", "state": "NC-7",
        "committees": ["Agriculture", "Transportation"],
        "known_sectors": ["Agriculture", "Infrastructure"],
        "notable": "Agriculture committee, trades in related sectors.",
    },
    "Rick Scott": {
        "party": "R", "chamber": "Senate", "state": "FL",
        "committees": ["Armed Services", "Commerce", "Budget"],
        "known_sectors": ["Healthcare", "Finance", "Defense"],
        "notable": "Former hospital CEO, one of wealthiest senators.",
    },
}

# Ticker-to-sector mapping for common stocks traded by congress
TICKER_SECTORS = {
    "NVDA": ["AI", "Semiconductors", "Tech"],
    "AAPL": ["Tech", "Consumer Electronics"],
    "MSFT": ["Tech", "AI", "Cloud"],
    "GOOGL": ["Tech", "AI", "Advertising"], "GOOG": ["Tech", "AI"],
    "META": ["Tech", "Social Media", "AI"],
    "AMZN": ["Tech", "E-commerce", "Cloud"],
    "TSLA": ["EV", "Energy", "Tech"],
    "LMT": ["Defense", "Aerospace"],
    "RTX": ["Defense", "Aerospace"],
    "NOC": ["Defense", "Aerospace"],
    "BA": ["Defense", "Aerospace"],
    "GD": ["Defense", "Aerospace"],
    "HII": ["Defense", "Shipbuilding"],
    "LHX": ["Defense", "Tech"],
    "JPM": ["Finance", "Banking"],
    "GS": ["Finance", "Banking"],
    "BAC": ["Finance", "Banking"],
    "XOM": ["Energy", "Oil"],
    "CVX": ["Energy", "Oil"],
    "PFE": ["Pharma", "Healthcare"],
    "JNJ": ["Pharma", "Healthcare"],
    "UNH": ["Healthcare", "Insurance"],
    "INTC": ["Semiconductors", "Tech"],
    "AMD": ["Semiconductors", "Tech", "AI"],
    "TSM": ["Semiconductors", "Tech"],
    "AVGO": ["Semiconductors", "Tech"],
    "CRM": ["Tech", "Cloud", "AI"],
    "DIS": ["Media", "Entertainment"],
    "NFLX": ["Media", "Streaming"],
}

# Keywords for matching markets to sectors/tickers
MARKET_KEYWORDS = {
    "AI": ["artificial intelligence", "ai regulation", "ai bill", "ai safety", "openai", "chatgpt"],
    "Semiconductors": ["chips", "semiconductor", "chip act", "chip ban", "chip export"],
    "Defense": ["defense spending", "military", "pentagon", "nato", "arms", "ukraine aid", "taiwan"],
    "Energy": ["oil", "gas", "energy", "drilling", "pipeline", "opec", "clean energy", "solar", "wind"],
    "Healthcare": ["healthcare", "medicare", "medicaid", "drug pricing", "pharma"],
    "Finance": ["banking", "fed", "interest rate", "wall street", "regulation", "crypto", "sec"],
    "Tech": ["big tech", "antitrust", "section 230", "tiktok", "data privacy", "tech regulation"],
    "EV": ["electric vehicle", "ev mandate", "ev subsidy", "tesla"],
}


# ---------------------------------------------------------------------------
# Data Fetching
# ---------------------------------------------------------------------------

def _fetch_quiver_quant(days_back: int = 7) -> Optional[List[dict]]:
    """Try Quiver Quant free API for recent congressional trades."""
    url = "https://api.quiverquant.com/beta/live/congresstrading"
    headers = {"Accept": "application/json", "User-Agent": "Pythia/1.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 403:
            logger.info("Quiver Quant requires auth, falling back")
            return None
        resp.raise_for_status()
        data = resp.json()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
        trades = []
        for item in data:
            trade_date_str = item.get("Date") or item.get("TransactionDate", "")
            try:
                td = datetime.fromisoformat(trade_date_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue
            if td < cutoff:
                continue
            name = item.get("Representative", item.get("Name", "Unknown"))
            profile = _lookup_profile(name)
            trades.append({
                "politician": name,
                "party": profile.get("party", item.get("Party", "?")),
                "chamber": profile.get("chamber", item.get("Chamber", "?")),
                "ticker": item.get("Ticker", "???"),
                "transaction_type": _normalize_txn(item.get("Transaction", "")),
                "amount_range": item.get("Range", item.get("Amount", "N/A")),
                "trade_date": trade_date_str,
                "disclosure_date": item.get("DisclosureDate", ""),
                "committees": profile.get("committees", []),
                "source": "quiver_quant",
            })
        return trades
    except Exception as e:
        logger.warning(f"Quiver Quant fetch failed: {e}")
        return None


def _fetch_capitol_trades(days_back: int = 7) -> Optional[List[dict]]:
    """Scrape Capitol Trades for recent congressional trades."""
    url = "https://www.capitoltrades.com/trades?per_page=96"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            logger.warning(f"Capitol Trades returned {resp.status_code}")
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        trades = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

        # Capitol Trades uses table rows or card elements
        rows = soup.select("table tbody tr") or soup.select(".trade-row")
        for row in rows:
            cells = row.select("td")
            if len(cells) < 6:
                continue
            try:
                politician_el = cells[0].get_text(strip=True)
                # Parse various table formats
                ticker_el = cells[1].get_text(strip=True) if len(cells) > 1 else ""
                # Extract ticker symbol (usually in caps, 1-5 chars)
                ticker_match = re.search(r'\b([A-Z]{1,5})\b', ticker_el)
                ticker = ticker_match.group(1) if ticker_match else ticker_el[:5]

                txn_type = cells[2].get_text(strip=True) if len(cells) > 2 else ""
                amount = cells[3].get_text(strip=True) if len(cells) > 3 else ""
                date_str = cells[4].get_text(strip=True) if len(cells) > 4 else ""

                # Try to parse date
                trade_date = None
                for fmt in ("%b %d, %Y", "%Y-%m-%d", "%m/%d/%Y", "%d %b %Y"):
                    try:
                        trade_date = datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
                        break
                    except ValueError:
                        continue

                if trade_date and trade_date < cutoff:
                    continue

                name = _clean_name(politician_el)
                profile = _lookup_profile(name)
                trades.append({
                    "politician": name,
                    "party": profile.get("party", "?"),
                    "chamber": profile.get("chamber", "?"),
                    "ticker": ticker,
                    "transaction_type": _normalize_txn(txn_type),
                    "amount_range": amount,
                    "trade_date": date_str,
                    "disclosure_date": "",
                    "committees": profile.get("committees", []),
                    "source": "capitol_trades",
                })
            except Exception as e:
                logger.debug(f"Error parsing Capitol Trades row: {e}")
                continue
        return trades if trades else None
    except Exception as e:
        logger.warning(f"Capitol Trades scrape failed: {e}")
        return None


def _normalize_txn(raw: str) -> str:
    raw_lower = raw.lower().strip()
    if "purchase" in raw_lower or "buy" in raw_lower:
        return "buy"
    if "sale" in raw_lower or "sell" in raw_lower:
        return "sell"
    if "exchange" in raw_lower:
        return "exchange"
    return raw_lower or "unknown"


def _clean_name(raw: str) -> str:
    """Clean politician name from scraped text."""
    # Remove titles and extra whitespace
    name = re.sub(r'^(Hon\.|Rep\.|Sen\.|Mr\.|Mrs\.|Ms\.)\s*', '', raw.strip())
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def _lookup_profile(name: str) -> dict:
    """Fuzzy match name against known profiles."""
    name_lower = name.lower()
    for pname, profile in POLITICIAN_PROFILES.items():
        if pname.lower() in name_lower or name_lower in pname.lower():
            return {**profile, "name": pname}
        # Check last name match
        last = pname.split()[-1].lower()
        if last in name_lower:
            return {**profile, "name": pname}
    return {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_recent_trades(days_back: int = 7) -> List[dict]:
    """Get recent congressional trades. Quiver Quant first, Capitol Trades fallback."""
    cache_key = f"trades_{days_back}d"
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.info(f"Returning {len(cached)} cached trades")
        return cached

    # Try Quiver Quant first
    trades = _fetch_quiver_quant(days_back)
    if not trades:
        logger.info("Quiver Quant unavailable, trying Capitol Trades")
        trades = _fetch_capitol_trades(days_back)
    if not trades:
        logger.warning("No trades from any source")
        trades = []

    _cache_set(cache_key, trades)
    return trades


def match_trades_to_markets(
    trades: List[dict], active_markets: List[dict]
) -> List[dict]:
    """Cross-reference trades with active prediction markets.
    
    Uses sector/keyword matching first, then LLM for ambiguous cases.
    Returns [{trade, market, relevance_score, explanation}]
    """
    if not trades or not active_markets:
        return []

    matches = []

    for trade in trades:
        ticker = trade.get("ticker", "").upper()
        sectors = TICKER_SECTORS.get(ticker, [])
        committees = trade.get("committees", [])
        politician = trade.get("politician", "")

        for market in active_markets:
            mq = (market.get("question", "") + " " + market.get("description", "")).lower()
            score = 0.0
            reasons = []

            # Sector match
            for sector in sectors:
                keywords = MARKET_KEYWORDS.get(sector, [])
                for kw in keywords:
                    if kw in mq:
                        score += 0.3
                        reasons.append(f"{ticker} is in {sector} sector, market mentions '{kw}'")
                        break

            # Direct ticker mention
            if ticker.lower() in mq or (len(ticker) > 2 and ticker.lower() in mq):
                score += 0.5
                reasons.append(f"Market directly mentions {ticker}")

            # Committee relevance
            for comm in committees:
                comm_lower = comm.lower()
                # Check if committee keywords appear in market
                comm_words = [w for w in comm_lower.split() if len(w) > 3]
                for w in comm_words:
                    if w in mq:
                        score += 0.2
                        reasons.append(f"Politician sits on {comm}")
                        break

            score = min(score, 1.0)

            if score >= 0.2:
                matches.append({
                    "trade": trade,
                    "market": market,
                    "relevance_score": round(score, 2),
                    "explanation": "; ".join(reasons) if reasons else "Potential relevance detected",
                })

    # For top ambiguous matches (score 0.2-0.4), use LLM for deeper assessment
    ambiguous = [m for m in matches if 0.2 <= m["relevance_score"] <= 0.4]
    if ambiguous and len(ambiguous) <= 5:
        matches = _llm_refine_matches(matches, ambiguous)

    matches.sort(key=lambda x: x["relevance_score"], reverse=True)
    return matches


def _llm_refine_matches(all_matches: List[dict], ambiguous: List[dict]) -> List[dict]:
    """Use Claude to refine ambiguous trade-market matches."""
    try:
        prompt_parts = []
        for i, m in enumerate(ambiguous):
            t = m["trade"]
            mk = m["market"]
            prompt_parts.append(
                f"{i+1}. {t['politician']} ({t['party']}) {t['transaction_type']} "
                f"{t['ticker']} ({t.get('amount_range', '?')})\n"
                f"   Committees: {', '.join(t.get('committees', ['Unknown']))}\n"
                f"   Market: \"{mk.get('question', mk.get('title', '?'))}\"\n"
                f"   Current initial assessment: {m['explanation']}"
            )

        prompt = (
            "Rate the relevance (0.0-1.0) of each congressional trade to its paired "
            "prediction market. Consider: insider knowledge potential, committee jurisdiction, "
            "sector overlap, timing. Reply as JSON array of objects with keys: "
            "index (1-based), score (float), explanation (brief).\n\n"
            + "\n".join(prompt_parts)
        )

        result = subprocess.run(
            ["claude", "--print", "--model", "sonnet", "-p", prompt],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            # Extract JSON from response
            text = result.stdout.strip()
            json_match = re.search(r'\[.*\]', text, re.DOTALL)
            if json_match:
                refined = json.loads(json_match.group())
                # Update scores
                ambig_map = {i: m for i, m in enumerate(ambiguous)}
                for r in refined:
                    idx = r.get("index", 0) - 1
                    if 0 <= idx < len(ambiguous):
                        ambiguous[idx]["relevance_score"] = round(float(r.get("score", 0.3)), 2)
                        ambiguous[idx]["explanation"] = r.get("explanation", ambiguous[idx]["explanation"])
    except Exception as e:
        logger.warning(f"LLM refinement failed: {e}")

    return all_matches


def get_politician_profile(name: str) -> dict:
    """Get politician profile: committees, trading record, known sectors."""
    profile = _lookup_profile(name)
    if profile:
        return profile
    return {
        "name": name,
        "party": "?",
        "chamber": "?",
        "committees": [],
        "known_sectors": [],
        "notable": "Not in top-20 tracked politicians database.",
    }


def detect_congressional_signal(active_markets: List[dict]) -> List[dict]:
    """Full pipeline: fetch trades → match to markets → score significance.
    
    Returns list of signals sorted by relevance score.
    """
    trades = fetch_recent_trades(days_back=7)
    if not trades:
        logger.info("No recent trades found")
        return []

    matches = match_trades_to_markets(trades, active_markets)

    # Enrich with disclosure delay info
    for m in matches:
        trade = m["trade"]
        try:
            td = _parse_date(trade.get("trade_date", ""))
            dd = _parse_date(trade.get("disclosure_date", ""))
            if td and dd:
                delay = (dd - td).days
                m["disclosure_delay_days"] = delay
                if delay > 30:
                    m["relevance_score"] = min(m["relevance_score"] + 0.1, 1.0)
                    m["explanation"] += f"; ⚠️ {delay}-day disclosure delay"
        except Exception:
            pass

    matches.sort(key=lambda x: x["relevance_score"], reverse=True)
    return matches


def _parse_date(s: str) -> Optional[datetime]:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%b %d, %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s.split("T")[0] if "T" in s else s, fmt)
        except ValueError:
            continue
    return None


def format_congressional_alert(signal: dict) -> str:
    """Format a congressional signal for Telegram."""
    trade = signal.get("trade", {})
    market = signal.get("market", {})

    politician = trade.get("politician", "Unknown")
    party = trade.get("party", "?")
    chamber = trade.get("chamber", "?")
    prefix = "Sen." if chamber == "Senate" else "Rep."

    ticker = trade.get("ticker", "???")
    txn = trade.get("transaction_type", "traded").upper()
    amount = trade.get("amount_range", "undisclosed amount")

    market_title = market.get("question", market.get("title", "Unknown market"))
    market_price = market.get("last_price", market.get("price", "?"))
    if isinstance(market_price, (int, float)):
        market_price = f"{market_price * 100:.0f}¢" if market_price <= 1 else f"{market_price}¢"

    committees = trade.get("committees", [])
    comm_str = ", ".join(committees) if committees else "N/A"

    score = signal.get("relevance_score", 0)
    score_bar = "🔴" if score >= 0.7 else "🟡" if score >= 0.4 else "⚪"

    delay = signal.get("disclosure_delay_days")
    delay_line = f"\n⚠️ Trade disclosed {delay} days after execution" if delay and delay > 14 else ""

    explanation = signal.get("explanation", "")
    explain_line = f"\n💡 {explanation}" if explanation else ""

    return (
        f"🏛️ CONGRESSIONAL SIGNAL {score_bar}\n"
        f"{prefix} {politician} ({party}) {txn} ${amount} of {ticker}\n"
        f"Related market: \"{market_title}\" (currently {market_price})\n"
        f"Committees: {comm_str}"
        f"{delay_line}"
        f"{explain_line}"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    if "--test-fetch" in sys.argv:
        trades = fetch_recent_trades(days_back=14)
        print(f"Found {len(trades)} trades:")
        for t in trades[:10]:
            print(f"  {t['politician']} {t['transaction_type']} {t['ticker']} ({t['amount_range']})")

    elif "--test-profile" in sys.argv:
        name = sys.argv[sys.argv.index("--test-profile") + 1] if len(sys.argv) > sys.argv.index("--test-profile") + 1 else "Pelosi"
        p = get_politician_profile(name)
        print(json.dumps(p, indent=2))

    elif "--test-format" in sys.argv:
        # Demo alert
        signal = {
            "trade": {
                "politician": "Tommy Tuberville",
                "party": "R",
                "chamber": "Senate",
                "ticker": "LMT",
                "transaction_type": "buy",
                "amount_range": "$50,001 - $100,000",
                "trade_date": "2026-01-15",
                "disclosure_date": "2026-03-01",
                "committees": ["Armed Services (Chair)"],
            },
            "market": {
                "question": "Will US increase defense spending by 10%?",
                "last_price": 0.62,
            },
            "relevance_score": 0.85,
            "disclosure_delay_days": 45,
            "explanation": "LMT is in Defense sector, market mentions 'defense spending'; Politician sits on Armed Services",
        }
        print(format_congressional_alert(signal))

    else:
        print("Usage: python congressional.py [--test-fetch|--test-profile NAME|--test-format]")
