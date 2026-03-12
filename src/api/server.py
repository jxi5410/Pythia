"""
Pythia API Server — Serves BACE attribution to the frontend.

Run locally:
    cd ~/Pythia
    uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --reload

Expose externally (for demos):
    ngrok http 8000

Then set PYTHIA_API_URL=https://xxxx.ngrok.io in Vercel env vars.
"""

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("pythia.api")

# ─── App ──────────────────────────────────────────────────────────────
app = FastAPI(title="Pythia API", version="1.0.0")

# CORS: allow Vercel frontend + localhost dev
ALLOWED_ORIGINS = [
    "https://pythia-demo.vercel.app",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
# Also allow any origin with PYTHIA_CORS_ORIGIN env var
extra_origin = os.environ.get("PYTHIA_CORS_ORIGIN")
if extra_origin:
    ALLOWED_ORIGINS.append(extra_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Request / Response models ────────────────────────────────────────
class SpikeInput(BaseModel):
    """Spike data from the frontend."""
    market_title: str
    market_id: str = ""
    timestamp: str  # ISO 8601
    direction: str  # "up" or "down"
    magnitude: float
    price_before: float
    price_after: float
    volume_at_spike: float = 0.0


class AttributeRequest(BaseModel):
    spike: SpikeInput
    depth: int = 2  # 1=fast, 2=standard, 3=deep


class EvidenceOut(BaseModel):
    source: str = ""
    title: str = ""
    url: Optional[str] = None
    timestamp: Optional[str] = None
    timing: str = "concurrent"  # before, concurrent, after


class HypothesisOut(BaseModel):
    agent: str
    cause: str
    confidence: float
    reasoning: str = ""
    evidence: List[EvidenceOut] = []
    impact_speed: str = ""
    counterfactual: str = ""


class AttributeResponse(BaseModel):
    success: bool
    depth: int
    agents_spawned: int
    hypotheses_proposed: int
    debate_rounds: int
    elapsed_seconds: float
    hypotheses: List[HypothesisOut]
    raw: Optional[Dict] = None  # full BACE output for debugging


# ─── SpikeProxy (matches what BACE expects) ──────────────────────────
@dataclass
class SpikeProxy:
    """Minimal spike object compatible with bace.attribute_spike()."""
    id: int = 0
    market_id: str = ""
    market_title: str = ""
    timestamp: str = ""
    direction: str = "up"
    magnitude: float = 0.0
    price_before: float = 0.0
    price_after: float = 0.0
    volume_at_spike: float = 0.0
    asset_class: str = ""
    attributed_events: list = field(default_factory=list)
    manual_tag: str = ""
    asset_reaction: dict = field(default_factory=dict)


# ─── Lazy-loaded LLM functions ────────────────────────────────────────
_llm_fast = None
_llm_strong = None


def _get_llm():
    global _llm_fast, _llm_strong
    if _llm_fast is None:
        from src.core.llm_integration import sonnet_call, opus_call
        _llm_fast = sonnet_call
        _llm_strong = opus_call
        logger.info("LLM functions loaded (backend: %s)", os.environ.get("PYTHIA_LLM_BACKEND", "not set"))
    return _llm_fast, _llm_strong


# ─── Health check ─────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/health/llm")
def health_llm():
    """Test LLM connectivity."""
    try:
        llm_fast, _ = _get_llm()
        result = llm_fast("Say 'ok' and nothing else.")
        return {"status": "ok", "llm_response": result[:50]}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ─── Main attribution endpoint ────────────────────────────────────────
@app.post("/api/attribute", response_model=AttributeResponse)
def attribute_spike_endpoint(req: AttributeRequest):
    """Run BACE attribution on a spike.

    This is the main endpoint the frontend calls when a user clicks a spike.
    Typical latency: 10-30s for depth 2 (mostly LLM API wait time).
    """
    logger.info("Attribution request: %s depth=%d mag=%.3f",
                req.spike.market_title[:40], req.depth, req.spike.magnitude)

    t0 = time.time()

    # Build spike proxy — strip timezone to naive UTC (BACE uses naive datetimes internally)
    ts_raw = req.spike.timestamp
    ts_raw = ts_raw.replace("Z", "+00:00")  # ensure fromisoformat handles it
    try:
        ts_dt = datetime.fromisoformat(ts_raw).replace(tzinfo=None)
        ts_clean = ts_dt.isoformat()
    except Exception:
        ts_clean = ts_raw  # pass through if parsing fails

    spike = SpikeProxy(
        id=0,
        market_id=req.spike.market_id or req.spike.market_title,
        market_title=req.spike.market_title,
        timestamp=ts_clean,
        direction=req.spike.direction,
        magnitude=req.spike.magnitude,
        price_before=req.spike.price_before,
        price_after=req.spike.price_after,
        volume_at_spike=req.spike.volume_at_spike,
    )

    # Get LLM functions
    try:
        llm_fast, llm_strong = _get_llm()
    except Exception as e:
        logger.error("LLM init failed: %s", e)
        raise HTTPException(status_code=503, detail=f"LLM not configured: {e}")

    # Run BACE
    try:
        from src.core.bace import attribute_spike, BACEDepth

        depth = max(1, min(3, req.depth))
        result = attribute_spike(
            spike=spike,
            all_recent_spikes=[],
            db=None,
            depth=depth,
            llm_fast=llm_fast,
            llm_strong=llm_strong,
        )
    except Exception as e:
        logger.error("BACE failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Attribution failed: {e}")

    elapsed = time.time() - t0
    logger.info("Attribution complete: %.1fs", elapsed)

    # Extract hypotheses from BACE result
    hypotheses = _extract_hypotheses(result)

    # Build response
    md = result.get("bace_metadata", {})
    return AttributeResponse(
        success=True,
        depth=result.get("bace_depth", depth),
        agents_spawned=md.get("agents_spawned", 0),
        hypotheses_proposed=md.get("hypotheses_proposed", len(hypotheses)),
        debate_rounds=md.get("debate_rounds", 0),
        elapsed_seconds=round(elapsed, 2),
        hypotheses=hypotheses,
        raw=result,
    )


def _extract_hypotheses(result: Dict) -> List[HypothesisOut]:
    """Extract structured hypotheses from BACE output.

    BACE output format varies by depth. This normalizes to a flat list.
    """
    hypotheses = []

    # Depth 1: single attribution in result["attribution"]
    attr = result.get("attribution", {})
    if attr and not result.get("agent_hypotheses"):
        hypotheses.append(HypothesisOut(
            agent="BACE (single-shot)",
            cause=attr.get("primary_cause", attr.get("cause", "Unknown")),
            confidence=_conf_to_float(attr.get("confidence", "LOW")),
            reasoning=attr.get("reasoning", attr.get("causal_chain", "")),
            impact_speed=attr.get("impact_speed", ""),
            counterfactual=attr.get("counterfactual", ""),
            evidence=_extract_evidence(attr),
        ))

    # Depth 2/3: agent_hypotheses list
    for h in result.get("agent_hypotheses", []):
        ev_list = []
        for e in h.get("evidence", []):
            if isinstance(e, dict):
                ev_list.append(EvidenceOut(
                    source=e.get("source", ""),
                    title=e.get("title", e.get("headline", str(e))),
                    url=e.get("url"),
                    timestamp=e.get("timestamp"),
                    timing=e.get("timing", "concurrent"),
                ))
            elif isinstance(e, str):
                ev_list.append(EvidenceOut(title=e))

        hypotheses.append(HypothesisOut(
            agent=h.get("agent", h.get("agent_name", "Unknown")),
            cause=h.get("hypothesis", h.get("cause", "")),
            confidence=_hyp_confidence(h),
            reasoning=h.get("reasoning", h.get("causal_chain", "")),
            impact_speed=h.get("impact_speed", h.get("timing", {}).get("impact_speed", "")),
            counterfactual=h.get("counterfactual", ""),
            evidence=ev_list,
        ))

    # Depth 3: synthesis may add final_attribution
    final = result.get("final_attribution", {})
    if final and final.get("cause") and not any(h.cause == final["cause"] for h in hypotheses):
        hypotheses.insert(0, HypothesisOut(
            agent="BACE Synthesis",
            cause=final.get("cause", ""),
            confidence=_conf_to_float(final.get("confidence", "MEDIUM")),
            reasoning=final.get("reasoning", ""),
            counterfactual=final.get("counterfactual", ""),
        ))

    # Sort by confidence descending
    hypotheses.sort(key=lambda h: h.confidence, reverse=True)
    return hypotheses


def _conf_to_float(conf) -> float:
    """Convert confidence string or number to float."""
    if isinstance(conf, (int, float)):
        return float(conf)
    return {"HIGH": 0.85, "MEDIUM": 0.55, "LOW": 0.25}.get(str(conf).upper(), 0.5)


def _hyp_confidence(h: Dict) -> float:
    """Extract confidence from a hypothesis dict."""
    c = h.get("confidence", h.get("confidence_score", 0.5))
    if isinstance(c, str):
        return _conf_to_float(c)
    return float(c)


def _extract_evidence(attr: Dict) -> List[EvidenceOut]:
    """Extract evidence from a depth-1 attribution result."""
    evidence = []
    for item in attr.get("evidence", attr.get("supporting_evidence", [])):
        if isinstance(item, dict):
            evidence.append(EvidenceOut(
                source=item.get("source", ""),
                title=item.get("title", item.get("headline", str(item))),
                url=item.get("url"),
                timing=item.get("timing", "concurrent"),
            ))
        elif isinstance(item, str):
            evidence.append(EvidenceOut(title=item))
    return evidence
