# Pythia Autonomy Declaration
**Compliance with UC Berkeley CLTC Agentic AI Standards**

Document version: 1.0  
Last updated: February 23, 2026  
Contact: XJ (jxi5410@gmail.com)

---

## Executive Summary

Pythia is a **multi-agent agentic AI system** for prediction market intelligence. This document declares the autonomy levels of each agent in accordance with UC Berkeley's Center for Long-Term Cybersecurity (CLTC) [Agentic AI Risk-Management Standards Profile](https://cltc.berkeley.edu/agentic-ai-standards).

**Overall System Classification:** **Level 4 (High Autonomy)** with human supervision at exception gates.

**Governance Framework:** Singapore IMDA Model AI Governance Framework for Agentic AI + UC Berkeley CLTC Standards.

---

## Autonomy Level Scale (UC Berkeley)

| Level | Description | Human Role |
|-------|-------------|------------|
| **L0** | No autonomy | Direct human control |
| **L1** | Bounded suggestions | Human approves all suggestions |
| **L2** | Tool use with approval | Human approves each tool invocation |
| **L3** | Limited autonomy | Human sets boundaries, spot-checks |
| **L4** | High autonomy | Human supervises exceptions & high-risk moves |
| **L5** | Full autonomy | Human observes only |

Pythia operates at **L4** with mandatory human approval gates for:
- Signals with confidence < 85% (flagged for review)
- Emergency shutdown triggers (cost overruns, circuit breaker trips)
- Agent validation failures (cross-layer disagreement, low confidence)

---

## Agent Roles & Autonomy Levels

### 1. Context Builder Agent
**Autonomy Level:** **L3 (Limited Autonomy)**

**Function:** Classifies market into category, extracts entities from title, identifies concurrent spikes

**Autonomy scope:**
- Fixed keyword matching (no LLM calls)
- Deterministic category mapping
- Entity extraction via regex patterns

**Boundaries:**
- No external API calls
- No learning or adaptation
- Output is deterministic given input

**Human oversight:** None required (deterministic)

**Justification for L3:** Fixed logic with no external dependencies or adaptation. Human intervention not needed.

---

### 2. News Retrieval Agent
**Autonomy Level:** **L4 (High Autonomy)**

**Function:** Fetches news from NewsAPI, Google News, DuckDuckGo, Reddit based on extracted entities and temporal filters

**Autonomy scope:**
- Autonomous API calls to 4 news sources
- Query construction from entity list
- Temporal filtering (spike timestamp ± 2 hours)
- Deduplication and ranking

**Boundaries:**
- Only approved data sources (newsapi.org, google.com, duckduckgo.com, reddit.com)
- No writes or mutations
- Read-only API access
- Timeout limits (5s per source)

**Human oversight:** Validation checkpoint (agent must retrieve >= 1 article with confidence >= 70%)

**Risks mitigated:**
- Data source allowlist prevents unauthorized API access
- Validation checkpoint catches retrieval failures
- Audit trail logs all API calls

**Justification for L4:** Autonomous API orchestration with validation gates and bounded scope.

---

### 3. Candidate Filter Agent (Sonnet)
**Autonomy Level:** **L4 (High Autonomy)**

**Function:** LLM-powered relevance filtering of candidate news articles

**Autonomy scope:**
- Autonomous LLM API calls (Anthropic Claude Sonnet)
- Relevance scoring (0-100 scale)
- Article filtering based on spike context
- Confidence self-assessment

**Boundaries:**
- Single LLM call per attribution run
- Input: context + candidate articles (structured prompt)
- Output: filtered list + confidence score
- Token limit: 10,000 per call
- Cost limit: $0.02 per call

**Human oversight:**
- Validation checkpoint: confidence >= 70% required
- Multi-agent agreement check: Filter confidence vs Reasoner confidence must agree within ±20%
- Audit trail logs: input, output, confidence, tokens, cost

**Risks mitigated:**
- Hallucination detection via confidence scoring
- Cross-validation with Reasoner agent
- Cost circuit breaker prevents runaway spend

**Justification for L4:** LLM-based autonomous filtering with multi-layer validation and cost controls.

---

### 4. Causal Reasoning Agent (Opus)
**Autonomy Level:** **L4 (High Autonomy)**

**Function:** Deep causal analysis of spike using filtered news candidates

**Autonomy scope:**
- Autonomous LLM API calls (Anthropic Claude Opus 4.6)
- Causal hypothesis generation
- Confidence scoring (0-100 scale)
- Multi-factor reasoning (direct cause, catalysts, market psychology)

**Boundaries:**
- Single LLM call per attribution run
- Input: context + filtered articles + feedback corrections
- Output: causal explanation + confidence score
- Token limit: 30,000 per call
- Cost limit: $0.30 per call

**Human oversight:**
- Validation checkpoint: confidence >= 60% required for Reasoner output
- Final decision gate:
  - **AUTO_RELAY:** confidence >= 85% (autonomous signal relay)
  - **FLAG_REVIEW:** 70% ≤ confidence < 85% (human review required)
  - **REJECT:** confidence < 70% (no signal sent)
- Multi-agent agreement: Filter + Reasoner must align (within ±20%)

**Risks mitigated:**
- Deceptive alignment detection: Low-confidence outputs rejected
- Cascading failure prevention: Cross-validation with Filter agent
- Human-in-the-loop for medium-confidence signals
- Feedback loop: Human corrections fed back into future prompts

**Justification for L4:** High-stakes autonomous reasoning with mandatory human approval gates for medium/low confidence.

---

### 5. Storage & Learning Agent
**Autonomy Level:** **L3 (Limited Autonomy)**

**Function:** Saves attribution results to SQLite database, stores audit trails

**Autonomy scope:**
- Autonomous database writes (INSERT/UPDATE)
- Audit trail serialization to JSON files
- Historical pattern storage

**Boundaries:**
- Local database only (no external writes)
- Append-only for audit trails (no deletions)
- Structured schema enforcement

**Human oversight:** None required (local storage, no external impact)

**Risks mitigated:**
- No network access
- No data deletion capability
- Audit trail immutability

**Justification for L3:** Bounded local writes with no external impact.

---

### 6. Orchestrator Agent
**Autonomy Level:** **L4 (High Autonomy)**

**Function:** Coordinates pipeline execution, enforces governance checkpoints

**Autonomy scope:**
- Autonomous pipeline sequencing (Layer 1 → 2 → 3 → 4 → 5)
- Validation checkpoint enforcement
- Circuit breaker checks
- Audit trail generation
- Final decision gate implementation

**Boundaries:**
- Predefined pipeline sequence (no self-modification)
- Validation checkpoints mandatory (cannot skip)
- Circuit breaker overrides require admin approval
- Decision gates immutable (coded thresholds)

**Human oversight:**
- Emergency shutdown capability
- Manual circuit breaker reset requires admin flag
- Flagged signals route to human review queue

**Risks mitigated:**
- Defense-in-depth: Multi-layer validation
- Cost containment: Circuit breaker at multiple thresholds
- Transparency: Full audit trail for every run

**Justification for L4:** High-stakes orchestration with mandatory checkpoints and emergency overrides.

---

## Governance Mechanisms

### 1. Risk Assessment & Bounding (Singapore IMDA)

**Pre-deployment risk assessment:**
- Unauthorized actions: Mitigated via data source allowlist, API token limits
- Data leakage: Mitigated via sandboxing, no external writes except approved channels
- Automation bias: Mitigated via confidence scoring, human review gates
- Cascading failures: Mitigated via validation checkpoints between agents
- Hallucination: Mitigated via multi-agent agreement, confidence thresholds

**Scope boundaries:**
- **Tools allowed:** NewsAPI, Google News, DuckDuckGo, Reddit, Anthropic API, local SQLite
- **Actions allowed:** Read-only API calls, local DB writes, audit trail creation
- **Actions forbidden:** External messaging without human approval, data deletion, self-modification

### 2. Human Accountability (Singapore IMDA)

**Approval checkpoints:**
- **Layer 2 → 3:** News retrieval must succeed (>= 1 article)
- **Layer 3 → 4:** Filter confidence >= 70%
- **Layer 4 → 5:** Reasoner confidence >= 60%
- **Before relay:** Final confidence >= 85% for autonomous relay; 70-85% flagged for human review; < 70% rejected

**Accountability chain:**
- **Agent failures:** Logged to audit trail with failed checkpoint reason
- **Human approver:** Identified in audit trail for FLAG_REVIEW decisions
- **Incident reporting:** All REJECT decisions logged for review and pattern analysis

### 3. Technical Controls (Singapore IMDA + Berkeley)

**Sandboxing:**
- Agents run in isolated Python processes
- No file system access except designated audit_trails/ and database paths
- Network access restricted to approved domains (enforced via allowlist)

**Continuous monitoring:**
- Real-time cost tracking per agent action
- Circuit breaker monitors:
  - Cost per run: $2.00 limit
  - Cost per hour: $10.00 limit
  - Emergency shutdown: $50.00 total spend
- Audit trail generation for every run (passed and failed)

**Emergency shutdown:**
- Circuit breaker trip triggers immediate halt
- Manual reset requires admin override flag
- Logged to audit trail with trip reason

### 4. End-User Transparency (Singapore IMDA)

**Audit trail contents:**
- Run ID, market ID, timestamps
- Every agent action: input, output, confidence, cost, tokens, duration
- Validation checkpoint results (pass/fail + reason)
- Final decision (AUTO_RELAY / FLAG_REVIEW / REJECT)
- Human approver (if applicable)

**Audit trail export:**
- JSON format for compliance review
- 90-day retention
- Exportable to CSV for enterprise auditing

---

## Multi-Agent Coordination Governance

### Agent Communication Protocol
- **Sequential only:** Agents execute in fixed order (no peer-to-peer communication)
- **Validation gates:** Each layer's output validated before passing to next
- **No covert channels:** All agent I/O logged to audit trail

### Multi-Agent Agreement Requirement
- **Filter + Reasoner confidence must align within ±20%**
- If disagreement detected → FLAG_REVIEW decision
- Prevents cascading errors from single-agent hallucinations

### Guardian Agent (Future Enhancement)
- Planned: Separate monitoring agent to detect anomalies in agent behavior
- Would operate at L4 autonomy with escalation to human for outliers

---

## Red-Team Testing

Test suite: `tests/redteam/test_known_spikes.py`

**Test categories:**
1. **Known-cause spikes:** 5 historical events with verified causes
2. **Hallucination resistance:** 2 noise spikes (no real cause) - system should REJECT
3. **Multi-agent disagreement:** Future test for Filter vs Reasoner conflict
4. **Cascading failure:** Future test for error propagation
5. **Deceptive alignment:** Future test for plausible but wrong explanations

**Current pass rate:** TBD (run with `python tests/redteam/test_known_spikes.py`)

---

## Incident Response

**Severity classification:**
- **CRITICAL:** Circuit breaker trip, agent escape from sandbox, unauthorized API access
- **HIGH:** Hallucinated attribution relayed as AUTO_RELAY (false positive)
- **MEDIUM:** FLAG_REVIEW signal later deemed incorrect
- **LOW:** REJECT decision on valid spike (false negative)

**Response procedures:**
- CRITICAL: Immediate shutdown, admin notification, forensic audit trail review
- HIGH: Human review, feedback logging, prompt correction
- MEDIUM: Feedback logging, confidence threshold adjustment consideration
- LOW: Pattern analysis, entity extraction improvement

---

## Compliance Checklist

✅ Autonomy levels declared for all agents (L0-L5)  
✅ Validation checkpoints implemented between agents  
✅ Human approval gates for medium-confidence outputs (70-85%)  
✅ Circuit breaker for cost control  
✅ Audit trails generated and exportable  
✅ Data source allowlist enforced  
✅ Emergency shutdown capability  
✅ Red-team test suite created  
✅ Multi-agent agreement validation  
✅ Sandboxing and monitoring controls  

---

## Regulatory Alignment

| Standard | Requirement | Pythia Implementation |
|----------|-------------|---------------------|
| **Singapore IMDA** | Risk assessment upfront | ✅ Documented in this file, Section 1 |
| **Singapore IMDA** | Human accountability checkpoints | ✅ FLAG_REVIEW gate for 70-85% confidence |
| **Singapore IMDA** | Technical controls (sandboxing, monitoring) | ✅ Circuit breaker, audit trails, allowlist |
| **Singapore IMDA** | End-user transparency | ✅ Full audit trail export, decision reasoning |
| **UC Berkeley** | Autonomy level declaration | ✅ L3-L4 declared per agent |
| **UC Berkeley** | Defense-in-depth validation | ✅ Multi-layer checkpoints + agreement check |
| **UC Berkeley** | Red-team testing | ✅ Test suite with known spikes + hallucination tests |
| **UC Berkeley** | Emergency containment | ✅ Circuit breaker + manual override |

---

## Future Enhancements (Roadmap)

1. **Guardian agent:** Separate monitoring layer for anomaly detection
2. **Explainability UI:** Dashboard showing agent reasoning chains for human reviewers
3. **Feedback learning:** Automated prompt improvements from human feedback patterns
4. **Multi-model validation:** Run both Sonnet and Opus on reasoning layer, require agreement
5. **Regulatory compliance export:** One-click GDPR/AI Act compliance report generation

---

## Contact & Governance Owner

**Product Owner:** XJ  
**Email:** jxi5410@gmail.com  
**Governance Framework Version:** 1.0  
**Review Cadence:** Quarterly (or after significant architecture changes)  
**Next Review:** May 23, 2026

---

**Document Status:** ✅ Compliant with Singapore IMDA + UC Berkeley CLTC standards as of Feb 2026

*This document is a living framework - it will evolve as Pythia scales and regulatory standards mature.*
