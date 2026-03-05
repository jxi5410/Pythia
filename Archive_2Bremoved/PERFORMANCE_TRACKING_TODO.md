# Pythia Performance Tracking Implementation

## Status: Mock Data (Dashboard Updated)

The Analysis tab now shows **forward testing performance metrics** instead of methodology.

**Current state:** Dashboard displays mock/example performance data to demonstrate what the tracking will look like.

---

## To Make It Real (Implementation Needed)

### 1. Database Schema Updates

Add to `signals` table:
```sql
ALTER TABLE signals ADD COLUMN outcome TEXT;  -- 'WIN', 'LOSS', 'PENDING', 'NEUTRAL'
ALTER TABLE signals ADD COLUMN realized_return REAL;  -- actual P&L when market resolves
ALTER TABLE signals ADD COLUMN resolution_date TEXT;  -- when outcome was determined
ALTER TABLE signals ADD COLUMN entry_price REAL;  -- price when signal fired
ALTER TABLE signals ADD COLUMN exit_price REAL;  -- price at resolution
```

### 2. Outcome Tracking Logic

Create `/src/pythia_live/performance_tracker.py`:
- Poll resolved markets daily
- Match back to original signals
- Calculate realized returns
- Update signal records with outcomes
- Store in performance_history table

### 3. Confidence Calibration

Track predicted vs actual:
- High confidence signals (>70%) → measure actual win rate
- Medium confidence (50-70%) → measure actual win rate
- Low confidence (<50%) → measure actual win rate
- Calculate calibration error

### 4. Performance Analytics

Functions to add to dashboard queries:
- `get_win_rate_by_signal_type()` - actual win rates, not expected
- `get_cumulative_returns()` - real time series of performance
- `get_best_worst_signals()` - actual top/bottom performers
- `get_sharpe_ratio()` - risk-adjusted returns
- `get_confidence_calibration()` - predicted vs actual

### 5. Data Pipeline

Daily job:
1. Fetch all resolved markets from last 7 days
2. Match to signals in database
3. Calculate outcomes (WIN/LOSS/NEUTRAL)
4. Update signal records
5. Recalculate aggregate stats
6. Store daily snapshot for time series

---

## Mock Data Currently Shown

**Metrics (all examples):**
- Win rate: 62.4%
- Avg return: 4.8% on wins, -2.1% on losses
- Sharpe ratio: 1.42
- Sample size: 195 signals, 133 resolved

**Replace with actual tracking once pipeline is live.**

---

## Priority

**Low for MVP** - Focus on:
1. Causal v2 working end-to-end
2. 30+ real attributions logged
3. Demo to Bangshan

**Medium for Design Partners** - Need real performance data when pitching to equity PMs.

**High for Paid Beta** - Can't charge without proof.

---

**Next step:** Build performance_tracker.py when Pythia is running consistently for 2+ weeks.
