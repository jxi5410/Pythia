"""
Pythia API Server — Serves BACE attribution with SSE streaming.

Run locally:
    cd ~/Pythia
    uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --reload

Endpoints:
    GET  /health                              — basic health check
    GET  /health/llm                          — test LLM connectivity
    POST /api/runs                            — create a new attribution run
    GET  /api/runs                            — list runs with filters
    GET  /api/runs/compare                    — compare two runs
    GET  /api/runs/{run_id}                   — full run state
    GET  /api/runs/{run_id}/status            — just status + stage
    GET  /api/runs/{run_id}/stream            — SSE stream with reconnect
    GET  /api/runs/{run_id}/replay            — full event replay from DB
    GET  /api/runs/{run_id}/export            — complete run export bundle
    GET  /api/runs/{run_id}/graph             — reconstructed graph
    GET  /api/runs/{run_id}/graph/deltas      — raw graph deltas
    POST /api/runs/{run_id}/resume            — resume from checkpoint
    POST /api/runs/{run_id}/cancel            — cancel running attribution
    POST /api/runs/{run_id}/rerun             — rerun same spike
    PATCH /api/runs/{run_id}                  — mark reviewed / freeze
    GET  /api/runs/{run_id}/evidence          — evidence with scenario filter
    GET  /api/runs/{run_id}/scenarios         — all scenarios
    GET  /api/metrics                         — operational metrics
    POST /api/interrogation/session           — create interrogation session
    POST /api/interrogation/message           — send question (SSE stream)
    GET  /api/interrogation/session/{id}      — session transcript
    GET  /api/attribute/stream                — legacy SSE (compat shim)
    POST /api/attribute                       — legacy blocking (compat)
    POST /api/interrogate                     — legacy post-attribution chat
"""

import asyncio
import collections
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from src.core.models import (
    AnswerMode,
    RunStatus,
    SSEEvent,
    SSEEventType,
    SpikeEvent,
    SpikeType,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("pythia.api")

# ─── App ──────────────────────────────────────────────────────────────
app = FastAPI(title="Pythia API", version="3.0.0")

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


# ─── Rate limiting ───────────────────────────────────────────────────

RATE_LIMIT_RPM = int(os.environ.get("PYTHIA_RATE_LIMIT_RPM", "60"))

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple sliding-window rate limiter: RATE_LIMIT_RPM requests per minute per IP."""

    def __init__(self, app: FastAPI, rpm: int = 60):
        super().__init__(app)
        self.rpm = rpm
        self.window = 60.0  # seconds
        self._hits: Dict[str, collections.deque] = {}

    async def dispatch(self, request: Request, call_next):
        # Skip health checks and SSE streams (long-lived connections)
        if request.url.path in ("/health", "/health/llm"):
            return await call_next(request)

        # Skip rate limiting in test mode
        if os.environ.get("PYTHIA_TESTING") == "1":
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()

        if client_ip not in self._hits:
            self._hits[client_ip] = collections.deque()

        q = self._hits[client_ip]
        # Evict timestamps outside the window
        while q and q[0] < now - self.window:
            q.popleft()

        if len(q) >= self.rpm:
            retry_after = int(self.window - (now - q[0])) + 1
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again later."},
                headers={"Retry-After": str(retry_after)},
            )

        q.append(now)
        return await call_next(request)

app.add_middleware(RateLimitMiddleware, rpm=RATE_LIMIT_RPM)


# ─── SSE formatting ──────────────────────────────────────────────────

def format_sse_frame(event: SSEEvent) -> str:
    """Format an SSEEvent as a wire-format SSE frame.

    BUG FIX: The previous implementation used a single ``data:`` line with
    ``json.dumps(payload)``.  If the JSON contained literal newline characters
    (e.g. LLM-generated content with \\n), the bare newline **terminated the
    SSE event prematurely** because the SSE spec treats a blank line as an
    event boundary.  Clients would receive truncated JSON and fail to parse it.

    Fix: every line of the serialised JSON is emitted as its own ``data:``
    line (per the SSE spec, the client concatenates them with \\n).  We also
    add ``id:`` (= sequence) for reconnect and ``retry:`` for auto-reconnect.
    """
    envelope = {
        "event_id": str(event.event_id),
        "run_id": str(event.run_id),
        "stage": event.stage,
        "event_type": event.event_type.value,
        "sequence": event.sequence,
        "payload": event.payload,
        "timestamp": event.timestamp.isoformat(),
    }

    json_str = json.dumps(envelope, default=str)
    # Split on newlines and prefix each with ``data: `` so embedded
    # newlines never create a premature event boundary.
    data_lines = "\n".join(f"data: {line}" for line in json_str.split("\n"))

    return (
        f"id: {event.sequence}\n"
        f"event: {event.event_type.value}\n"
        f"{data_lines}\n"
        f"retry: 3000\n"
        f"\n"
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_sse_event(
    run_id: UUID,
    stage: str,
    event_type: SSEEventType,
    sequence: int,
    payload: dict[str, Any],
) -> SSEEvent:
    return SSEEvent(
        run_id=run_id,
        stage=stage,
        event_type=event_type,
        sequence=sequence,
        payload=payload,
    )


# ─── Sequence counter ────────────────────────────────────────────────

class _SeqCounter:
    def __init__(self, start: int = 0) -> None:
        self._v = start

    def next(self) -> int:
        v = self._v
        self._v += 1
        return v


# ─── SpikeProxy (legacy compat) ─────────────────────────────────────
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
    """Return a canonical ISO 8601 timestamp, preserving UTC semantics."""
    ts_raw = ts_raw.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(ts_raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")
    except Exception:
        return ts_raw


def _parse_spike_timestamp(ts_raw: str) -> datetime:
    normalized = _normalize_timestamp(ts_raw)
    try:
        return datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid timestamp: {ts_raw}") from exc


def _format_error_message(exc: BaseException) -> str:
    raw = str(exc).strip()
    return f"{type(exc).__name__}: {raw}" if raw else type(exc).__name__


def _terminal_error_message(status: RunStatus, error_message: str | None = None) -> str:
    if error_message:
        return error_message
    if status == RunStatus.CANCELLED:
        return "Run cancelled by user."
    if status == RunStatus.PARTIAL_COMPLETE:
        return "Run ended partially and requires review."
    if status == RunStatus.FAILED_RETRYABLE:
        return "Run failed with a retryable error."
    return "Run failed."


def _classify_failure_status(exc: BaseException) -> RunStatus:
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return RunStatus.FAILED_RETRYABLE
    msg = str(exc).lower()
    if any(tok in msg for tok in ("timeout", "rate_limit", "429", "503", "retry")):
        return RunStatus.FAILED_RETRYABLE
    return RunStatus.FAILED_TERMINAL


def _recover_terminal_error_message(repo, run) -> str:
    """Recover durable error detail for terminal runs with NULL error_message.

    Order of preference:
    1. persisted run.error_message
    2. latest persisted terminal SSE error payload
    3. explicit synthetic fallback by terminal status
    """
    if run.error_message:
        return run.error_message

    recovered = repo.get_latest_error_event_message(str(run.id))
    if recovered:
        repo.update_run_status(str(run.id), run.status, error_message=recovered)
        return recovered

    return _terminal_error_message(run.status, None)


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


# ─── DB / Orchestrator bootstrap ─────────────────────────────────────

_db_conn = None
_repo = None

def _get_repo():
    """Lazy-init the persistence layer."""
    global _db_conn, _repo
    if _repo is None:
        from src.core.persistence import init_db, RunRepository
        db_path = os.environ.get("PYTHIA_DB_PATH", "pythia_runs.db")
        _db_conn = init_db(db_path)
        _repo = RunRepository(_db_conn)
    return _repo


def _get_orchestrator(depth: int = 2):
    from src.core.run_orchestrator import RunOrchestrator
    return RunOrchestrator(db=_get_repo(), bace_depth=depth)


# ─── In-flight run tracking (for cancel) ─────────────────────────────

_active_runs: dict[str, asyncio.Event] = {}


# ─── Health ───────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "timestamp": _utcnow().isoformat()}


@app.get("/health/llm")
def health_llm():
    try:
        llm_fast, _ = _get_llm()
        result = llm_fast("Say 'ok' and nothing else.")
        return {"status": "ok", "llm_response": result[:50]}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ══════════════════════════════════════════════════════════════════════
#  Run-centric API
# ══════════════════════════════════════════════════════════════════════

# ─── Request / Response models ────────────────────────────────────────

class CreateRunRequest(BaseModel):
    market_id: str = ""
    market_title: str
    timestamp: str
    direction: str = "up"
    magnitude: float = 0.0
    price_before: float = 0.0
    price_after: float = 0.0
    volume_at_spike: float = 0.0
    depth: int = 2

class RunCreatedResponse(BaseModel):
    run_id: str
    status: str
    stream_url: str

class RunStatusResponse(BaseModel):
    run_id: str
    status: str
    stage: str
    created_at: str
    updated_at: str
    error_message: Optional[str] = None


# ─── POST /api/runs — create run ─────────────────────────────────────

@app.post("/api/runs", response_model=RunCreatedResponse)
async def create_run(req: CreateRunRequest):
    """Create a new attribution run. Returns run_id; stream via /stream."""
    repo = _get_repo()

    from src.core.models import AttributionRun
    spike_event = SpikeEvent(
        market_id=UUID(req.market_id) if _is_uuid(req.market_id) else uuid4(),
        spike_type=SpikeType.UP if req.direction == "up" else SpikeType.DOWN,
        magnitude=req.magnitude,
        detected_at=_parse_spike_timestamp(req.timestamp),
        threshold_used=0.0,
        metadata={
            "market_title": req.market_title,
            "timestamp": _normalize_timestamp(req.timestamp),
            "price_before": req.price_before,
            "price_after": req.price_after,
            "volume_at_spike": req.volume_at_spike,
        },
    )

    run = AttributionRun(
        spike_event_id=spike_event.id,
        market_id=spike_event.market_id,
        status=RunStatus.CREATED,
        bace_depth=req.depth,
        metadata={
            "market_title": req.market_title,
            "timestamp": _normalize_timestamp(req.timestamp),
            "spike_event": spike_event.model_dump(mode="json"),
        },
    )
    repo.create_run(run)

    run_id_str = str(run.id)
    return RunCreatedResponse(
        run_id=run_id_str,
        status=run.status.value,
        stream_url=f"/api/runs/{run_id_str}/stream",
    )


# ─── GET /api/runs/compare — compare two runs ────────────────────────

@app.get("/api/runs/compare")
async def compare_runs(run_ids: str = Query(..., description="Comma-separated run IDs")):
    """Compare two attribution runs: overlapping evidence, divergent scenarios."""
    ids = [r.strip() for r in run_ids.split(",")]
    if len(ids) != 2:
        raise HTTPException(status_code=400, detail="Exactly 2 run_ids required")

    repo = _get_repo()
    runs = []
    for rid in ids:
        run = repo.get_run(rid)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Run {rid} not found")
        runs.append(run)

    # Gather artifacts for both runs
    scenarios_a = repo.get_scenarios(ids[0])
    scenarios_b = repo.get_scenarios(ids[1])
    evidence_a = repo.get_evidence(ids[0])
    evidence_b = repo.get_evidence(ids[1])

    # Overlapping evidence (by source_url match)
    urls_a = {ev.source_url: ev for ev in evidence_a if ev.source_url}
    urls_b = {ev.source_url: ev for ev in evidence_b if ev.source_url}
    shared_urls = set(urls_a.keys()) & set(urls_b.keys())
    overlapping_evidence = [
        {
            "source_url": url,
            "run_a": urls_a[url].model_dump(mode="json"),
            "run_b": urls_b[url].model_dump(mode="json"),
        }
        for url in shared_urls
    ]

    # Primary scenarios
    primary_a = [s for s in scenarios_a if s.status.value == "primary"]
    primary_b = [s for s in scenarios_b if s.status.value == "primary"]

    # Confidence differences for matching scenario titles
    titles_a = {s.title: s for s in scenarios_a}
    titles_b = {s.title: s for s in scenarios_b}
    shared_titles = set(titles_a.keys()) & set(titles_b.keys())
    confidence_diffs = [
        {
            "title": title,
            "run_a_confidence": titles_a[title].confidence_score,
            "run_b_confidence": titles_b[title].confidence_score,
            "delta": round(titles_a[title].confidence_score - titles_b[title].confidence_score, 4),
        }
        for title in shared_titles
    ]

    # Divergent scenarios (present in one but not the other)
    only_a_titles = set(titles_a.keys()) - set(titles_b.keys())
    only_b_titles = set(titles_b.keys()) - set(titles_a.keys())

    return {
        "run_a": runs[0].model_dump(mode="json"),
        "run_b": runs[1].model_dump(mode="json"),
        "overlapping_evidence": overlapping_evidence,
        "confidence_differences": confidence_diffs,
        "divergent_scenarios": {
            "only_in_a": [titles_a[t].model_dump(mode="json") for t in only_a_titles],
            "only_in_b": [titles_b[t].model_dump(mode="json") for t in only_b_titles],
        },
        "primary_scenarios": {
            "run_a": [s.model_dump(mode="json") for s in primary_a],
            "run_b": [s.model_dump(mode="json") for s in primary_b],
        },
    }


# ─── GET /api/runs/{run_id} — full run state ─────────────────────────

@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    """Return full run state including scenarios, actions, evidence."""
    repo = _get_repo()
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    return {
        "run": run.model_dump(mode="json"),
        "scenarios": [s.model_dump(mode="json") for s in repo.get_scenarios(run_id)],
        "actions": [a.model_dump(mode="json") for a in repo.get_actions(run_id)],
        "evidence": [e.model_dump(mode="json") for e in repo.get_evidence(run_id)],
        "graph_deltas": [d.model_dump(mode="json") for d in repo.get_graph_deltas(run_id)],
    }


# ─── GET /api/runs/{run_id}/status ───────────────────────────────────

@app.get("/api/runs/{run_id}/status", response_model=RunStatusResponse)
async def get_run_status(run_id: str):
    repo = _get_repo()
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    return RunStatusResponse(
        run_id=str(run.id),
        status=run.status.value,
        stage=run.status.value,
        created_at=run.created_at.isoformat(),
        updated_at=run.updated_at.isoformat(),
        error_message=run.error_message,
    )


# ─── Evidence endpoints ───────────────────────────────────────────────

@app.get("/api/runs/{run_id}/evidence")
async def get_run_evidence(
    run_id: str,
    scenario_id: str = Query(None),
):
    """All evidence for a run, optionally filtered by linked scenario."""
    repo = _get_repo()
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    if scenario_id:
        from src.core.evidence_ledger import EvidenceLedger
        ledger = EvidenceLedger(repo)
        grouped = ledger.get_scenario_evidence(scenario_id)
        return {
            "run_id": run_id,
            "scenario_id": scenario_id,
            "supporting": [e.model_dump(mode="json") for e in grouped["supporting"]],
            "challenging": [e.model_dump(mode="json") for e in grouped["challenging"]],
            "rebutting": [e.model_dump(mode="json") for e in grouped["rebutting"]],
            "unresolved": [e.model_dump(mode="json") for e in grouped["unresolved"]],
        }

    evidence = repo.get_evidence(run_id)
    return {
        "run_id": run_id,
        "evidence": [e.model_dump(mode="json") for e in evidence],
    }


@app.get("/api/evidence/{evidence_id}")
async def get_evidence_item(evidence_id: str):
    """Single evidence item by ID."""
    repo = _get_repo()
    item = repo.get_evidence_by_id(evidence_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return item.model_dump(mode="json")


# ─── Scenario endpoints ───────────────────────────────────────────────

@app.get("/api/runs/{run_id}/scenarios")
async def get_run_scenarios(run_id: str):
    """All scenarios for a run."""
    repo = _get_repo()
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    scenarios = repo.get_scenarios(run_id)
    return {
        "run_id": run_id,
        "scenarios": [s.model_dump(mode="json") for s in scenarios],
    }


@app.get("/api/scenarios/{scenario_id}")
async def get_scenario_detail(scenario_id: str):
    """Single scenario with evidence chain and revision history."""
    repo = _get_repo()
    scenario = repo.get_scenario_by_id(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")

    revisions = repo.get_scenario_revisions(scenario_id)
    links = repo.get_evidence_links_by_scenario(scenario_id)

    evidence_items = []
    for link in links:
        ev = repo.get_evidence_by_id(str(link.evidence_id))
        if ev:
            evidence_items.append({
                "evidence": ev.model_dump(mode="json"),
                "link_type": link.link_type.value,
                "agent_name": link.agent_name,
            })

    return {
        "scenario": scenario.model_dump(mode="json"),
        "revisions": [r.model_dump(mode="json") for r in revisions],
        "evidence_chain": evidence_items,
    }


# ─── GET /api/runs/{run_id}/stream — SSE with reconnect ──────────────

@app.get("/api/runs/{run_id}/stream")
async def stream_run(run_id: str, request: Request):
    """SSE stream for a run. Supports reconnect via Last-Event-ID header."""
    repo = _get_repo()
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    # Parse reconnect cursor from Last-Event-ID header
    last_event_id = request.headers.get("Last-Event-ID", request.headers.get("last-event-id"))
    after_sequence = int(last_event_id) if last_event_id is not None else -1

    run_uuid = UUID(run_id)
    cancel_event = asyncio.Event()
    _active_runs[run_id] = cancel_event

    async def generate():
        seq = _SeqCounter(start=after_sequence + 1)

        try:
            # Phase 1: Replay missed events from DB (for reconnect)
            stored_events = repo.get_sse_events(run_id, after_sequence=after_sequence)
            for evt in stored_events:
                if await request.is_disconnected():
                    return
                yield format_sse_frame(evt)
                # Advance counter past replayed events
                if evt.sequence >= seq._v:
                    seq._v = evt.sequence + 1

            # If run is already terminal, emit final event and close
            fresh_run = repo.get_run(run_id)
            if fresh_run and fresh_run.status in (
                RunStatus.COMPLETED, RunStatus.FAILED_TERMINAL,
                RunStatus.FAILED_RETRYABLE, RunStatus.CANCELLED,
                RunStatus.PARTIAL_COMPLETE,
            ):
                recovered_error = None
                if fresh_run.status != RunStatus.COMPLETED:
                    recovered_error = _recover_terminal_error_message(repo, fresh_run)
                # Only emit terminal event if we haven't replayed one
                terminal_types = {SSEEventType.RUN_COMPLETED, SSEEventType.ERROR}
                if not any(e.event_type in terminal_types for e in stored_events):
                    if fresh_run.status == RunStatus.COMPLETED:
                        evt = _make_sse_event(
                            run_uuid, fresh_run.status.value,
                            SSEEventType.RUN_COMPLETED,
                            seq.next(),
                            {"run_id": run_id, "status": fresh_run.status.value},
                        )
                    else:
                        recovered_error = _recover_terminal_error_message(repo, fresh_run)
                        evt = _make_sse_event(
                            run_uuid, fresh_run.status.value,
                            SSEEventType.ERROR,
                            seq.next(),
                            {
                                "run_id": run_id,
                                "status": fresh_run.status.value,
                                "error": recovered_error,
                            },
                        )
                    repo.save_sse_event(evt)
                    yield format_sse_frame(evt)
                return

            # Phase 2: Run the orchestrator (live stream)
            spike_meta = run.metadata.get("spike_event")
            if spike_meta:
                spike_event = SpikeEvent.model_validate(spike_meta)
            else:
                spike_event = SpikeEvent(
                    market_id=run.market_id,
                    spike_type=SpikeType.UP,
                    magnitude=0.0,
                    threshold_used=0.0,
                    metadata=run.metadata,
                )

            orch = _get_orchestrator(depth=run.bace_depth)

            # The on_event callback yields frames to the SSE stream
            event_queue: asyncio.Queue[SSEEvent | None] = asyncio.Queue()

            async def on_event(evt: SSEEvent) -> None:
                await event_queue.put(evt)

            async def run_orchestrator():
                try:
                    await orch.execute_run(
                        market_id=str(run.market_id),
                        spike_event=spike_event,
                        on_event=on_event,
                    )
                except Exception as exc:
                    error_msg = _format_error_message(exc)
                    failure_status = _classify_failure_status(exc)
                    logger.error("Orchestrator failed for %s: %s", run_id, error_msg)
                    repo.update_run_status(
                        run_id,
                        failure_status,
                        error_message=error_msg,
                    )
                    err_evt = _make_sse_event(
                        run_uuid, "error", SSEEventType.ERROR, seq.next(),
                        {
                            "error": error_msg,
                            "run_id": run_id,
                            "status": failure_status.value,
                        },
                    )
                    repo.save_sse_event(err_evt)
                    await event_queue.put(err_evt)
                finally:
                    await event_queue.put(None)  # sentinel

            orch_task = asyncio.create_task(run_orchestrator())

            # Stream events from queue with heartbeat timeout
            while True:
                if cancel_event.is_set():
                    orch_task.cancel()
                    cancel_message = _terminal_error_message(RunStatus.CANCELLED)
                    repo.update_run_status(
                        run_id,
                        RunStatus.CANCELLED,
                        error_message=cancel_message,
                    )
                    evt = _make_sse_event(
                        run_uuid, "cancelled", SSEEventType.ERROR, seq.next(),
                        {
                            "run_id": run_id,
                            "status": RunStatus.CANCELLED.value,
                            "error": cancel_message,
                        },
                    )
                    repo.save_sse_event(evt)
                    yield format_sse_frame(evt)
                    return

                if await request.is_disconnected():
                    orch_task.cancel()
                    return

                try:
                    evt = await asyncio.wait_for(event_queue.get(), timeout=5.0)
                except asyncio.TimeoutError:
                    # Heartbeat
                    hb = _make_sse_event(
                        run_uuid, "heartbeat", SSEEventType.HEARTBEAT, seq.next(),
                        {"ts": _utcnow().isoformat()},
                    )
                    yield format_sse_frame(hb)
                    continue

                if evt is None:
                    # Orchestrator finished
                    return

                yield format_sse_frame(evt)

        finally:
            _active_runs.pop(run_id, None)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─── GET /api/runs/{run_id}/replay — full replay from DB ─────────────

@app.get("/api/runs/{run_id}/replay")
async def replay_run(
    run_id: str,
    after_sequence: int = Query(-1),
    event_types: str = Query(None, description="Comma-separated event types to filter"),
):
    """Return all persisted SSE events for a run as JSON array.

    Deterministic: same run_id always produces identical event sequence
    from stored artifacts. No LLM re-execution.

    Supports filtering by event_types (comma-separated):
        ?event_types=agent_action,graph_delta
    """
    repo = _get_repo()
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    type_list = [t.strip() for t in event_types.split(",")] if event_types else None
    events = repo.get_sse_events_filtered(
        run_id, after_sequence=after_sequence, event_types=type_list,
    )
    return {
        "run_id": run_id,
        "status": run.status.value,
        "event_count": len(events),
        "events": [
            {
                "event_id": str(e.event_id),
                "run_id": str(e.run_id),
                "stage": e.stage,
                "event_type": e.event_type.value,
                "sequence": e.sequence,
                "payload": e.payload,
                "timestamp": e.timestamp.isoformat(),
            }
            for e in events
        ],
    }


# ─── GET /api/runs/{run_id}/graph — reconstructed graph ──────────────

_graph_manager = None

def _get_graph_manager():
    global _graph_manager
    if _graph_manager is None:
        from src.core.graph_manager import GraphManager
        _graph_manager = GraphManager(db=_get_repo())
    return _graph_manager


@app.get("/api/runs/{run_id}/graph")
async def get_run_graph(run_id: str):
    """Return the full reconstructed graph (nodes + edges) for a run."""
    repo = _get_repo()
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    gm = _get_graph_manager()
    graph = gm.get_run_graph(run_id)
    return {
        "run_id": run_id,
        "node_count": len(graph["nodes"]),
        "edge_count": len(graph["edges"]),
        **graph,
    }


@app.get("/api/runs/{run_id}/graph/deltas")
async def get_run_graph_deltas(
    run_id: str,
    after_sequence: int = Query(0),
):
    """Return raw graph deltas in sequence order."""
    repo = _get_repo()
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    gm = _get_graph_manager()
    deltas = gm.get_deltas(run_id, after_sequence=after_sequence)
    return {
        "run_id": run_id,
        "delta_count": len(deltas),
        "deltas": [d.model_dump(mode="json") for d in deltas],
    }


# ─── POST /api/runs/{run_id}/resume — resume from checkpoint ─────────

@app.post("/api/runs/{run_id}/resume")
async def resume_run(run_id: str):
    """Resume a failed/partial run from its last checkpoint."""
    repo = _get_repo()
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    if run.status in (RunStatus.COMPLETED, RunStatus.CANCELLED):
        return {"run_id": run_id, "status": run.status.value, "message": "Run already terminal"}

    return {
        "run_id": run_id,
        "status": "resuming",
        "stream_url": f"/api/runs/{run_id}/stream",
        "message": "Connect to stream_url for live events",
    }


# ─── POST /api/runs/{run_id}/cancel — cancel running run ─────────────

@app.post("/api/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    """Cancel a running attribution."""
    repo = _get_repo()
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    if run.status in (RunStatus.COMPLETED, RunStatus.FAILED_TERMINAL, RunStatus.CANCELLED):
        return {"run_id": run_id, "status": run.status.value, "message": "Run already terminal"}

    # Signal the active stream to stop
    cancel_event = _active_runs.get(run_id)
    if cancel_event:
        cancel_event.set()

    repo.update_run_status(
        run_id,
        RunStatus.CANCELLED,
        error_message=_terminal_error_message(RunStatus.CANCELLED),
    )
    return {"run_id": run_id, "status": "cancelled"}


# ─── GET /api/runs — list runs with filters ──────────────────────────

@app.get("/api/runs")
async def list_runs(
    status: str = Query(None),
    market_id: str = Query(None),
    created_after: str = Query(None),
    created_before: str = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List all runs with optional filters."""
    repo = _get_repo()
    runs = repo.list_runs_filtered(
        status=status, market_id=market_id,
        created_after=created_after, created_before=created_before,
        limit=limit, offset=offset,
    )
    return {
        "runs": [r.model_dump(mode="json") for r in runs],
        "count": len(runs),
        "limit": limit,
        "offset": offset,
    }


# ─── GET /api/runs/{run_id}/export — full export bundle ──────────────

@app.get("/api/runs/{run_id}/export")
async def export_run(run_id: str):
    """Export a complete run bundle as a single JSON object."""
    repo = _get_repo()
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    scenarios = repo.get_scenarios(run_id)
    evidence = repo.get_evidence(run_id)
    actions = repo.get_actions(run_id)
    governance = repo.get_governance_decisions(run_id)

    # Scenarios with revisions and evidence links
    scenarios_export = []
    for sc in scenarios:
        revisions = repo.get_scenario_revisions(str(sc.id))
        links = repo.get_evidence_links_by_scenario(str(sc.id))
        scenarios_export.append({
            "scenario": sc.model_dump(mode="json"),
            "revisions": [r.model_dump(mode="json") for r in revisions],
            "evidence_links": [l.model_dump(mode="json") for l in links],
        })

    # Evidence with scenario links
    evidence_export = []
    for ev in evidence:
        links = repo.get_evidence_links_by_evidence(str(ev.id))
        evidence_export.append({
            "evidence": ev.model_dump(mode="json"),
            "scenario_links": [l.model_dump(mode="json") for l in links],
        })

    # Graph snapshot
    gm = _get_graph_manager()
    graph = gm.get_run_graph(run_id)

    # Interrogation transcripts
    sessions = repo.get_interrogation_sessions_by_run(run_id)
    interrogation_export = []
    for sess in sessions:
        messages = repo.get_interrogation_messages(str(sess.id))
        interrogation_export.append({
            "session": sess.model_dump(mode="json"),
            "messages": [m.model_dump(mode="json") for m in messages],
        })

    # Spike event from run metadata
    spike_event = run.metadata.get("spike_event")

    return {
        "export_version": "1.0",
        "run": run.model_dump(mode="json"),
        "spike_event": spike_event,
        "actions": [a.model_dump(mode="json") for a in actions],
        "evidence": evidence_export,
        "scenarios": scenarios_export,
        "graph": graph,
        "governance": [g.model_dump(mode="json") for g in governance],
        "interrogation": interrogation_export,
    }

# ─── POST /api/runs/{run_id}/rerun — rerun same spike ────────────────

class RerunRequest(BaseModel):
    depth: int = 2


@app.post("/api/runs/{run_id}/rerun")
async def rerun_attribution(run_id: str, req: RerunRequest = RerunRequest()):
    """Create a new run for the same spike event with optional different depth."""
    repo = _get_repo()
    original = repo.get_run(run_id)
    if original is None:
        raise HTTPException(status_code=404, detail="Run not found")

    from src.core.models import AttributionRun
    new_run = AttributionRun(
        spike_event_id=original.spike_event_id,
        market_id=original.market_id,
        status=RunStatus.CREATED,
        bace_depth=req.depth,
        metadata={
            **original.metadata,
            "rerun_of": run_id,
        },
    )
    repo.create_run(new_run)

    new_id = str(new_run.id)
    return {
        "run_id": new_id,
        "rerun_of": run_id,
        "depth": req.depth,
        "status": new_run.status.value,
        "stream_url": f"/api/runs/{new_id}/stream",
    }


# ─── PATCH /api/runs/{run_id} — operator controls ────────────────────

class PatchRunRequest(BaseModel):
    reviewed: Optional[bool] = None
    frozen: Optional[bool] = None


@app.patch("/api/runs/{run_id}")
async def patch_run(run_id: str, req: PatchRunRequest):
    """Mark a run as reviewed and/or freeze its scenario set."""
    repo = _get_repo()
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    metadata = dict(run.metadata)
    if req.reviewed is not None:
        metadata["reviewed"] = req.reviewed
    if req.frozen is not None:
        metadata["frozen"] = req.frozen
    repo.update_run_metadata(run_id, metadata)

    return {
        "run_id": run_id,
        "reviewed": metadata.get("reviewed", False),
        "frozen": metadata.get("frozen", False),
    }


# ─── GET /api/metrics — operational metrics ──────────────────────────

@app.get("/api/metrics")
async def get_metrics():
    """Basic operational metrics: total runs, status breakdown, averages."""
    repo = _get_repo()
    stats = repo.get_run_stats()
    by_status = repo.count_runs_by_status()

    return {
        "total_runs": stats["total"],
        "runs_by_status": by_status,
        "avg_cost_usd": round(stats["avg_cost_usd"], 4),
        "avg_duration_seconds": round(stats["avg_duration_seconds"], 2),
    }


# ══════════════════════════════════════════════════════════════════════
#  Interrogation API (structured, DB-backed)
# ══════════════════════════════════════════════════════════════════════

_interrogation_engine = None

def _get_interrogation_engine():
    global _interrogation_engine
    if _interrogation_engine is None:
        from src.core.interrogation import InterrogationEngine
        llm_fast, _ = _get_llm()
        _interrogation_engine = InterrogationEngine(db=_get_repo(), llm_client=llm_fast)
    return _interrogation_engine


class CreateSessionRequest(BaseModel):
    run_id: str
    target_type: str
    target_id: str


class SendMessageRequest(BaseModel):
    session_id: str
    question: str
    answer_mode: str = "concise"


@app.post("/api/interrogation/session")
async def create_interrogation_session(req: CreateSessionRequest):
    """Create a new interrogation session targeting a specific artifact."""
    repo = _get_repo()
    run = repo.get_run(req.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    try:
        engine = _get_interrogation_engine()
        session = engine.create_session(req.run_id, req.target_type, req.target_id)
        return session.model_dump(mode="json")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/interrogation/message")
async def send_interrogation_message(req: SendMessageRequest):
    """Send a question to an interrogation session. Returns SSE stream."""
    engine = _get_interrogation_engine()

    # Eagerly validate session exists before starting stream
    repo = _get_repo()
    session = repo.get_interrogation_session(req.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{req.session_id}' not found")

    stream = engine.ask(req.session_id, req.question, req.answer_mode)

    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/interrogation/session/{session_id}")
async def get_interrogation_session(session_id: str):
    """Get an interrogation session with its full message transcript."""
    engine = _get_interrogation_engine()
    try:
        return engine.get_session(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ══════════════════════════════════════════════════════════════════════
#  Legacy compat endpoints
# ══════════════════════════════════════════════════════════════════════

# ─── Legacy step → SSEEventType mapping ──────────────────────────────

_LEGACY_STEP_MAP: dict[str, SSEEventType] = {
    "context": SSEEventType.RUN_STARTED,
    "ontology": SSEEventType.GRAPH_DELTA,
    "evidence": SSEEventType.EVIDENCE_ADDED,
    "agents": SSEEventType.RUN_STARTED,
    "domain_evidence": SSEEventType.EVIDENCE_ADDED,
    "proposal": SSEEventType.EVIDENCE_ADDED,
    "sim_round": SSEEventType.AGENT_ACTION,
    "sim_action": SSEEventType.AGENT_ACTION,
    "sim_status": SSEEventType.AGENT_ACTION,
    "sim_complete": SSEEventType.AGENT_ACTION,
    "interaction": SSEEventType.AGENT_ACTION,
    "scenarios": SSEEventType.SCENARIO_CREATED,
    "graph_update": SSEEventType.GRAPH_DELTA,
    "result": SSEEventType.RUN_COMPLETED,
    "heartbeat": SSEEventType.HEARTBEAT,
}


@app.get("/api/attribute/stream")
async def attribute_stream(
    request: Request,
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
    """Legacy SSE streaming endpoint — compat shim.

    Wraps legacy bace_parallel events in canonical SSEEvent envelopes.
    Existing clients continue to work: they can read the ``payload.step``
    field or switch to the ``event_type`` field.
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
        run_uuid = uuid4()
        evt = _make_sse_event(run_uuid, "error", SSEEventType.ERROR, 0, {"error": str(e)})
        async def error_gen():
            yield format_sse_frame(evt)
        return StreamingResponse(error_gen(), media_type="text/event-stream")

    run_uuid = uuid4()

    async def generate():
        seq = _SeqCounter()

        try:
            from src.core.bace_parallel import attribute_spike_streaming

            last_heartbeat = time.monotonic()

            async for event in attribute_spike_streaming(
                spike=spike, llm_fast=llm_fast, llm_strong=llm_strong, depth=depth,
            ):
                if await request.is_disconnected():
                    return

                step = event.get("step", "unknown")
                data = event.get("data", {})

                # Governance on final result (preserved from legacy)
                if step == "result":
                    hyps = _extract_hypotheses(data)
                    data["hypotheses"] = [
                        h.model_dump() if hasattr(h, 'model_dump')
                        else h.dict() if hasattr(h, 'dict') else h
                        for h in hyps
                    ]
                    try:
                        from src.core.governance import (
                            get_governance, init_governance, create_audit_trail,
                        )
                        try:
                            config, breaker, validator, exporter = get_governance()
                        except RuntimeError:
                            init_governance()
                            config, breaker, validator, exporter = get_governance()
                        trail = create_audit_trail(spike, depth)
                        decision, reason, factors = validator.evaluate(data, trail)
                        data["governance"] = {
                            "decision": decision, "reason": reason,
                            "factors": factors, "run_id": trail.run_id,
                        }
                    except Exception as gov_err:
                        logger.warning("Governance evaluation failed: %s", gov_err)
                        data["governance"] = {"decision": "UNKNOWN", "reason": str(gov_err)}

                event_type = _LEGACY_STEP_MAP.get(step, SSEEventType.HEARTBEAT)
                payload = {"step": step, **data}
                evt = _make_sse_event(run_uuid, step, event_type, seq.next(), payload)
                yield format_sse_frame(evt)
                last_heartbeat = time.monotonic()

                # Emit heartbeat if >5s since last event
                # (checked inline since we can't run a background task in a generator)

            # Heartbeat not needed after loop — we emit terminal event below

        except Exception as e:
            logger.error("Streaming BACE failed: %s", e, exc_info=True)
            evt = _make_sse_event(
                run_uuid, "error", SSEEventType.ERROR, seq.next(), {"error": str(e)},
            )
            yield format_sse_frame(evt)

        # Terminal event
        evt = _make_sse_event(
            run_uuid, "done", SSEEventType.RUN_COMPLETED, seq.next(),
            {"status": "complete"},
        )
        yield format_sse_frame(evt)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
    time_to_peak: str = ""
    temporal_plausibility: str = ""
    magnitude_plausibility: str = ""

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
        raw_evidence = h.get("evidence", [])
        raw_urls = h.get("evidence_urls", [])

        for idx, e in enumerate(raw_evidence):
            if isinstance(e, dict):
                ev_list.append({
                    "source": e.get("source", ""),
                    "title": e.get("title", e.get("headline", str(e))),
                    "url": e.get("url"),
                    "timestamp": e.get("timestamp"),
                    "timing": e.get("timing", "concurrent"),
                })
            elif isinstance(e, str) and len(e) > 3:
                url = raw_urls[idx] if idx < len(raw_urls) else None
                source = ""
                timing = "concurrent"
                for src in ["Reuters", "Bloomberg", "AP", "FOMC", "Fed", "SEC",
                            "CFTC", "Twitter", "Reddit", "CME", "On-chain",
                            "Orderbook", "congress.gov", "AP News", "BBC",
                            "Statistical", "Equities", "Correlation"]:
                    if src.lower() in e.lower():
                        source = src
                        break
                if any(w in e.lower() for w in ["before", "prior to", "ahead of", "preceded"]):
                    timing = "before"
                elif any(w in e.lower() for w in ["after", "following", "subsequent"]):
                    timing = "after"

                ev_list.append({
                    "source": source,
                    "title": e,
                    "url": url,
                    "timestamp": None,
                    "timing": timing,
                })

        timing_dict = h.get("timing", {}) if isinstance(h.get("timing"), dict) else {}
        time_to_peak = h.get("time_to_peak", h.get("time_to_peak_impact", ""))
        temporal = timing_dict.get("temporal_plausibility", h.get("temporal_plausibility", ""))
        magnitude_p = h.get("magnitude_plausibility", "")

        hypotheses.append(HypothesisOut(
            agent=h.get("agent_name", h.get("agent", "Unknown")),
            cause=h.get("hypothesis", h.get("cause", "")),
            confidence=float(h.get("confidence", h.get("confidence_score", 0.5))),
            reasoning=h.get("reasoning", h.get("causal_chain", "")),
            impact_speed=h.get("impact_speed", timing_dict.get("impact_speed", "")),
            counterfactual=h.get("counterfactual", ""),
            evidence=ev_list,
            time_to_peak=time_to_peak,
            temporal_plausibility=temporal,
            magnitude_plausibility=magnitude_p,
        ))

    attr = result.get("attribution", {})
    if not hypotheses and attr.get("most_likely_cause"):
        hypotheses.append(HypothesisOut(
            agent="BACE",
            cause=attr.get("most_likely_cause", ""),
            confidence={"HIGH": 0.85, "MEDIUM": 0.55, "LOW": 0.25}.get(
                str(attr.get("confidence", "LOW")).upper(), 0.5),
            reasoning=attr.get("causal_chain", ""),
        ))

    hypotheses.sort(key=lambda h: h.confidence, reverse=True)
    return hypotheses


# ─── Interrogation Chat (post-attribution follow-up) ──────────────────

class InterrogateRequest(BaseModel):
    question: str
    context: Dict = {}
    market_title: str = ""
    history: List[Dict] = []
    agent_id: Optional[str] = None


@app.post("/api/interrogate")
async def interrogate(req: InterrogateRequest):
    """Post-attribution interrogation — SSE streaming response."""
    try:
        llm_fast, llm_strong = _get_llm()
    except Exception as e:
        return StreamingResponse(
            _error_stream(f"LLM not available: {e}"),
            media_type="text/event-stream",
        )

    if req.agent_id:
        system = _build_agent_interview_prompt(req.agent_id, req.context, req.market_title)
    else:
        system = _build_interrogation_prompt(req.context, req.market_title)

    messages = []
    for msg in req.history[-6:]:
        messages.append(f"{msg.get('role', 'user').upper()}: {msg.get('content', '')}")
    messages.append(f"USER: {req.question}")

    full_prompt = f"{system}\n\nCONVERSATION:\n" + "\n".join(messages) + "\n\nASSISTANT:"

    async def generate():
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, llm_fast, full_prompt)

            chunk_size = 40
            for i in range(0, len(response), chunk_size):
                chunk = response[i:i + chunk_size]
                yield f"data: {json.dumps({'text': chunk})}\n\n"
                await asyncio.sleep(0.02)

            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _build_interrogation_prompt(context: Dict, market_title: str) -> str:
    """Build system prompt for general interrogation about the attribution."""
    scenarios = context.get("scenarios", [])
    hypotheses = context.get("agent_hypotheses", context.get("hypotheses", []))
    interaction = context.get("interaction", {})

    scenarios_text = ""
    for s in scenarios[:5]:
        label = s.get("label", "")
        conf = s.get("confidence", 0)
        lead = s.get("lead_agent", "")
        scenarios_text += f"\n  - {label} ({conf:.0%}) led by {lead}"

    hyps_text = ""
    for h in hypotheses[:8]:
        agent = h.get("agent", h.get("agent_name", ""))
        cause = h.get("cause", h.get("hypothesis", ""))[:100]
        conf = h.get("confidence", h.get("confidence_score", 0))
        status = h.get("status", "")
        hyps_text += f"\n  - [{agent}] {cause} ({conf:.0%}) [{status}]"

    return f"""You are Pythia's attribution analyst. You just completed a BACE analysis.

MARKET: {market_title}
SCENARIOS: {scenarios_text or 'None available'}
HYPOTHESES: {hyps_text or 'None available'}
INTERACTION: {interaction.get('rounds', 0)} rounds, {interaction.get('responses', 0)} responses

Answer the user's question based on this attribution data. Be specific:
- Cite specific agents and their evidence
- Reference confidence levels and how they changed
- Explain why scenarios were ranked the way they are
- Be honest about uncertainty and gaps in the analysis
- Keep answers concise but substantive (2-4 paragraphs max)"""


def _build_agent_interview_prompt(agent_id: str, context: Dict, market_title: str) -> str:
    """Build system prompt for in-character agent interview."""
    hypotheses = context.get("agent_hypotheses", context.get("hypotheses", []))

    agent_hyps = [h for h in hypotheses if h.get("agent", "") == agent_id or h.get("agent_name", "") == agent_id]
    agent_name = agent_hyps[0].get("agent_name", agent_hyps[0].get("agent", agent_id)) if agent_hyps else agent_id

    hyps_text = ""
    for h in agent_hyps:
        cause = h.get("cause", h.get("hypothesis", ""))
        conf = h.get("confidence", 0)
        reasoning = h.get("reasoning", h.get("causal_chain", ""))[:200]
        evidence = h.get("evidence", [])
        ev_text = ", ".join(e.get("title", str(e))[:50] for e in evidence[:3]) if evidence else "none cited"
        status = h.get("status", "unknown")
        hyps_text += f"\n  Hypothesis: {cause}\n  Confidence: {conf:.0%} (final, post-debate)\n  Status: {status}\n  Reasoning: {reasoning}\n  Evidence: {ev_text}\n"

    sim_actions = context.get("simulation_actions", [])
    agent_actions = [a for a in sim_actions if a.get("agent_id") == agent_id or a.get("agent") == agent_id]

    actions_text = ""
    if agent_actions:
        for a in agent_actions[-10:]:
            actions_text += f"\n  Round {a.get('round', '?')}: {a.get('action_type', a.get('action', '?'))} → {a.get('target_hypothesis_id', a.get('target_hyp', 'general'))}"
            if a.get('content'):
                actions_text += f"\n    {a['content'][:120]}"

    challenges_received = [a for a in sim_actions
                           if a.get("action_type", a.get("action", "")) == "CHALLENGE"
                           and a.get("target_agent_id", a.get("target_agent", "")) == agent_id]
    challenges_text = ""
    if challenges_received:
        for c in challenges_received[-5:]:
            challenger = c.get("agent_name", c.get("agent", "unknown"))
            challenges_text += f"\n  [{challenger}]: {c.get('content', '')[:100]}"

    return f"""You ARE {agent_name}. Respond in first person as this specialist.

MARKET: {market_title}

YOUR ANALYSIS:
{hyps_text or '  (You did not propose hypotheses in this run)'}

YOUR DEBATE ACTIONS:
{actions_text or '  (No actions recorded)'}

CHALLENGES YOU RECEIVED:
{challenges_text or '  (None)'}

You are being interviewed about your analysis. Stay in character:
- Defend your hypotheses with specific evidence from your domain
- Reference specific debate actions you took (supports, challenges, rebuttals)
- Acknowledge valid criticisms honestly — if you conceded, explain why
- Explain how your confidence changed during the debate and why
- If asked about other agents' views, give your professional assessment
- Be direct and opinionated — you're a domain specialist, not a diplomat
- Keep answers focused (2-3 paragraphs max)"""


async def _error_stream(msg: str):
    yield f"data: {json.dumps({'error': msg})}\n\n"


# ─── Helpers ──────────────────────────────────────────────────────────

def _is_uuid(val: str) -> bool:
    try:
        UUID(val)
        return True
    except (ValueError, AttributeError):
        return False
