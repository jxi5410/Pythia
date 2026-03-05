# AGENT_ARCHITECTURE_V2.md — XJ.ai Operating System

## Overview

7 specialized agents + 1 orchestrator. Flat subscriptions (Claude Max, Gemini, Kimi) mean no marginal cost per token. Model routing based purely on **capability**, not cost.

## Agents

| Agent | Short Name | Model | Purpose |
|-------|-----------|-------|---------|
| ChiefOfStaff | `chief` | Opus 4.6 | Orchestration, routing, state management |
| CodeBuilder | `code` | Opus 4.6 | MVP dev, GitHub integration, testing |
| CareerNavigator | `career` | Opus 4.6 | Job monitoring, interview prep, skills tracking |
| VentureStrategist | `venture` | Opus 4.6 | Startup ideation, pitch prep, market analysis |
| ShadowBoard | `board` | Opus 4.6 | 5-persona advisory board that challenges ideas |
| SideHustleManager | `hustle` | Sonnet 4.6 | Cadenza CRM, feedback, compliance, suppliers |
| MarketIntel | `intel` | Sonnet 4.6 | Pythia ops, pattern monitoring, signals |

## Model Routing (Capability-Based)

| Task | Model | Why |
|------|-------|-----|
| Strategy, reasoning, ideation | Opus 4.6 | Best quality, no cost penalty |
| Coding, architecture, deep analysis | Opus 4.6 | Best quality, no cost penalty |
| Interview prep, career strategy | Opus 4.6 | Best quality, no cost penalty |
| Routine monitoring, CRM checks | Sonnet 4.6 | Fast, capable, speed > depth |
| Real-time data processing | Sonnet 4.6 | Latency matters more than depth |

**Principle:** Flat subscriptions = use the best model for everything. Sonnet only where speed/latency is the bottleneck.

## Commands

```bash
python3 swarm.py status                     # All agents
python3 swarm.py run code status            # CodeBuilder scan
python3 swarm.py run career jobs            # LinkedIn check
python3 swarm.py run hustle status          # Cadenza CRM
python3 swarm.py run intel patterns         # Pythia patterns
python3 swarm.py heartbeat                  # Run proactive checks
python3 swarm.py route "build X"            # Route task to agent
python3 swarm.py challenge "idea text"      # Shadow board
python3 swarm.py idea                       # Generate startup idea
```

## Heartbeat Schedule

| Time | Agent | Action |
|------|-------|--------|
| 7:00 | venture | Generate 1 startup idea |
| 8:00 | career | Check LinkedIn for AI roles |
| 9:00 | chief | Daily TODO summary |
| 12:00 | intel | Pythia pattern check |
| 18:00 | hustle | Cadenza feedback/supplier check |
| 21:00 | chief | Daily summary |
