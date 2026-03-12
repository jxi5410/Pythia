"""
Pythia API Server — Serves BACE attribution with SSE streaming.

Run locally:
    cd ~/Pythia
    uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --reload

Endpoints:
    GET  /health          — basic health check
    GET  /health/llm      — test LLM connectivity
    POST /api/attribute   — blocking attribution (original, kept for compat)
    GET  /api/attribute/stream — SSE streaming attribution (new, preferred)
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("pythia.api")

# ─── App ──────────────────────────────────────────────────────────────
app = FastAPI(title="Pythia API", version="2.0.0")

ALLOWED_ORIGINS = [
    "https://pythia-demo.vercel.app",
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
]
extra = os.environ.get("PYTHIA_CORS_ORIGIN")
if extra:
    ALLOWED_ORIGINS.append(extra)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── SpikeProxy ───────────────────────────────────────────────────────
@dataclass
class SpikeProxy:
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


def _normalize_timestamp(ts_raw: str) -> str:
    """Strip timezone to naive UTC."""
    ts_raw = ts_raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(ts_raw).replace(tzinfo=None)
        return dt.isoformat()
    except Exception:
        return ts_raw


# ─── LLM ──────────────────────────────────────────────────────────────
_llm_fast = None
_llm_strong = None

def _get_llm():
    global _llm_fast, _llm_strong
    if _llm_fast is None:
        from src.core.llm_integration import sonnet_call, opus_call
        _llm_fast = sonnet_call
        _llm_strong = opus_call
        logger.info("LLM loaded (backend: %s)", os.environ.get("PYTHIA_LLM_BACKEND", "not set"))
    return _llm_fast, _llm_strong


# ─── Health ───────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/health/llm")
def health_llm():
    try:
        llm_fast, _ = _get_llm()
        result = llm_fast("Say 'ok' and nothing else.")
        return {"status": "ok", "llm_response": result[:50]}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ─── SSE Streaming Attribution (preferred) ────────────────────────────
@app.get("/api/attribute/stream")
async def attribute_stream(
    market_title: str = Query(...),
    market_id: str = Query(""),
    timestamp: str = Query(...),
    direction: str = Query(...),
    magnitude: float = Query(...),
    price_before: float = Query(...),
    price_after: float = Query(...),
    volume_at_spike: float = Query(0),
    depth: int = Query(2),
):
    """SSE streaming endpoint for BACE attribution.

    The frontend opens an EventSource connection. Each BACE step emits
    a server-sent event with the step name and data. The final event
    contains the full attribution result.
    """
    spike = SpikeProxy(
        market_id=market_id or market_title,
        market_title=market_title,
        timestamp=_normalize_timestamp(timestamp),
        direction=direction,
        magnitude=magnitude,
        price_before=price_before,
        price_after=price_after,
        volume_at_spike=volume_at_spike,
    )

    try:
        llm_fast, llm_strong = _get_llm()
    except Exception as e:
        async def error_stream():
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")

    async def generate():
        try:
            from src.core.bace_parallel import attribute_spike_streaming

            async for event in attribute_spike_streaming(
                spike=spike,
                llm_fast=llm_fast,
                llm_strong=llm_strong,
                depth=depth,
            ):
                step = event.get("step", "unknown")
                data = event.get("data", {})

                # For the final result, also extract hypotheses and run governance
                if step == "result":
                    hyps = _extract_hypotheses(data)
                    # Convert Pydantic models to dicts for JSON serialization
                    data["hypotheses"] = [h.model_dump() if hasattr(h, 'model_dump') else h.dict() if hasattr(h, 'dict') else h for h in hyps]

                    # Run governance decision gate
                    try:
                        from src.core.governance import (
                            get_governance, init_governance, create_audit_trail,
                            GovernanceConfig,
                        )
                        try:
                            config, breaker, validator, exporter = get_governance()
                        except RuntimeError:
                            init_governance()
                            config, breaker, validator, exporter = get_governance()

                        trail = create_audit_trail(spike, depth)
                        decision, reason, factors = validator.evaluate(data, trail)
                        data["governance"] = {
                            "decision": decision,
                            "reason": reason,
                            "factors": factors,
                            "run_id": trail.run_id,
                        }
                    except Exception as gov_err:
                        logger.warning("Governance evaluation failed: %s", gov_err)
                        data["governance"] = {"decision": "UNKNOWN", "reason": str(gov_err)}

                yield f"event: {step}\ndata: {json.dumps(data, default=str)}\n\n"

        except Exception as e:
            logger.error("Streaming BACE failed: %s", e, exc_info=True)
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

        yield f"event: done\ndata: {json.dumps({'status': 'complete'})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ─── Blocking Attribution (compat) ────────────────────────────────────
class SpikeInput(BaseModel):
    market_title: str
    market_id: str = ""
    timestamp: str
    direction: str
    magnitude: float
    price_before: float
    price_after: float
    volume_at_spike: float = 0.0

class AttributeRequest(BaseModel):
    spike: SpikeInput
    depth: int = 2

class HypothesisOut(BaseModel):
    agent: str
    cause: str
    confidence: float
    reasoning: str = ""
    evidence: list = []
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
    raw: Optional[Dict] = None


@app.post("/api/attribute", response_model=AttributeResponse)
async def attribute_spike_endpoint(req: AttributeRequest):
    """Blocking endpoint — collects all SSE events and returns final result."""
    spike = SpikeProxy(
        market_id=req.spike.market_id or req.spike.market_title,
        market_title=req.spike.market_title,
        timestamp=_normalize_timestamp(req.spike.timestamp),
        direction=req.spike.direction,
        magnitude=req.spike.magnitude,
        price_before=req.spike.price_before,
        price_after=req.spike.price_after,
        volume_at_spike=req.spike.volume_at_spike,
    )

    try:
        llm_fast, llm_strong = _get_llm()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"LLM not configured: {e}")

    try:
        from src.core.bace_parallel import attribute_spike_streaming

        result = None
        async for event in attribute_spike_streaming(
            spike=spike, llm_fast=llm_fast, llm_strong=llm_strong, depth=req.depth,
        ):
            if event.get("step") == "result":
                result = event["data"]

        if not result:
            raise HTTPException(status_code=500, detail="No result from BACE")

        hypotheses = _extract_hypotheses(result)
        md = result.get("bace_metadata", {})

        return AttributeResponse(
            success=True,
            depth=req.depth,
            agents_spawned=md.get("agents_spawned", 0),
            hypotheses_proposed=md.get("hypotheses_proposed", len(hypotheses)),
            debate_rounds=md.get("debate_rounds", 0),
            elapsed_seconds=md.get("elapsed_seconds", 0),
            hypotheses=hypotheses,
            raw=result,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("BACE failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ─── Hypothesis extraction ────────────────────────────────────────────

def _extract_hypotheses(result: Dict) -> List[HypothesisOut]:
    hypotheses = []

    for h in result.get("agent_hypotheses", []):
        ev_list = []
        for e in h.get("evidence", []):
            if isinstance(e, dict):
                ev_list.append({
                    "source": e.get("source", ""),
                    "title": e.get("title", e.get("headline", str(e))),
                    "url": e.get("url"),
                    "timestamp": e.get("timestamp"),
                    "timing": e.get("timing", "concurrent"),
                })
            elif isinstance(e, str):
                ev_list.append({"title": e})

        hypotheses.append(HypothesisOut(
            agent=h.get("agent_name", h.get("agent", "Unknown")),
            cause=h.get("hypothesis", h.get("cause", "")),
            confidence=float(h.get("confidence", h.get("confidence_score", 0.5))),
            reasoning=h.get("reasoning", h.get("causal_chain", "")),
            impact_speed=h.get("impact_speed", h.get("timing", {}).get("impact_speed", "") if isinstance(h.get("timing"), dict) else ""),
            counterfactual=h.get("counterfactual", ""),
            evidence=ev_list,
        ))

    # Fallback for depth 1
    attr = result.get("attribution", {})
    if not hypotheses and attr.get("most_likely_cause"):
        hypotheses.append(HypothesisOut(
            agent="BACE",
            cause=attr.get("most_likely_cause", ""),
            confidence={"HIGH": 0.85, "MEDIUM": 0.55, "LOW": 0.25}.get(str(attr.get("confidence", "LOW")).upper(), 0.5),
            reasoning=attr.get("causal_chain", ""),
        ))

    hypotheses.sort(key=lambda h: h.confidence, reverse=True)
    return hypotheses
