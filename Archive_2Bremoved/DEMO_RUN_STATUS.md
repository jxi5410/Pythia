# Pythia Demo Run - Live Tracking

**Started:** Feb 23, 2026, ~11:45 AM GMT  
**Duration:** 7 days (target: collect 10+ spike attributions)  
**Purpose:** Generate real demo cases for design partner deck

---

## Status

**Process:** ✅ Running (PID: 47201)  
**Sources:** Kalshi ✅ | Polymarket ✅ | Manifold ⚠️ (limited support)  
**Logs:** `logs/pythia_demo_run_20260223.log`  
**Demo cases:** `demo_cases/spikes_20260223.jsonl`

**To check:**
```bash
# Is Pythia running?
ps -p $(cat /tmp/pythia_demo.pid)

# View logs
tail -f logs/pythia_demo_run_20260223.log

# Track spikes detected
./scripts/track_demo_cases.sh

# Stop
kill $(cat /tmp/pythia_demo.pid)
```

---

## Goals

**Collect 10+ real spike attributions with:**
- Market name + source
- Direction (up/down) + magnitude
- Causal attribution (what caused it)
- Confidence score
- Cross-asset signals (if any)
- Timestamp (when detected vs when Bloomberg reported)

**Use cases:**
1. Design partner pitch deck (slide 6: real example)
2. Proof-first cold emails
3. Bangshan demo
4. Case studies for website

---

## What Makes a Good Demo Case

**Criteria:**
- ✅ High confidence (85%+)
- ✅ Significant magnitude (10%+ move)
- ✅ Clear causal attribution (not "unknown")
- ✅ Lead time vs Bloomberg (detected 15+ min early)
- ✅ Relevant to target ICP (Fed, elections, crypto, geopolitics)

**Avoid:**
- ❌ Low-liquidity markets (< $10K)
- ❌ Obscure topics (celebrity gossip, sports unless major)
- ❌ Low confidence (< 70%)

---

## Expected Output (Next 7 Days)

**Daily cycle:** ~48 cycles/day (30min poll interval)  
**Expected spikes:** 1-3 per day (varies by market volatility)  
**Target:** 10-15 quality attributions by March 2

**Review cadence:**
- Daily: Check `demo_cases/spikes_*.jsonl` for new entries
- Every 2 days: Pick top 3-5 for deck
- Day 7: Final selection of best 10 examples

---

## Current Demo Cases

_(Will update as spikes are detected)_

**Day 1 (Feb 23):**
- _Monitoring started 11:45 AM GMT_
- _No spikes detected yet (markets stable)_

**Day 2 (Feb 24):**
- TBD

**Day 3 (Feb 25):**
- TBD

_(XJ.ai will update this file daily)_

---

## Next Steps After Collection

1. **Select top 10 attributions** (highest confidence, best narratives)
2. **Create slide visuals** (screenshots or mockups for deck slide 6)
3. **Write case studies** (1 detailed example for proof-first emails)
4. **Update design partner deck** (add real examples to slide 10)
5. **Demo to Bangshan** (show live results)

---

**Owner:** XJ.ai  
**Last updated:** Feb 23, 2026, 11:45 AM GMT  
**Status:** 🔴 LIVE - Collecting demo cases
