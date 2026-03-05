# PMXT Integration Plan for Pythia

## Context

Pythia's frontend (`pythia-demo`) currently uses hardcoded mock market data in its Next.js API routes. The PMXT library (`npm install pmxtjs`) provides a unified API for fetching real-time market data from Polymarket, Kalshi, and other prediction market exchanges — replacing mock data with live feeds. This integration replaces the static mock layer while preserving Pythia's existing signal detection (Python backend) and UI components.

**Deployment**: Node.js server (`next start`) — PMXT sidecar works natively.

## Key PMXT Facts

- **Install**: `npm install pmxtjs`
- **Import**: `import pmxt from 'pmxtjs'`
- **Architecture**: Runs a background sidecar server (Node.js process)
- **Key methods**: `fetchMarkets({ limit, offset, sort, query, slug })`, `fetchEvents({ query })`, OHLCV candle data
- **Data hierarchy**: Events → Markets → Outcomes (yes/no with prices)
- **Sort options**: `volume`, `liquidity`, `newest`
- **Read-only**: No credentials needed for data fetching
- **Historical data**: OHLCV candles available (hourly resolution)

---

## Implementation Steps

### Step 1: Install PMXT and create service layer

**File**: `pythia-demo/lib/pmxt.ts` (new)

Create a singleton service that:
- Initializes PMXT exchanges (Polymarket + Kalshi)
- Manages sidecar lifecycle (start on first call, reuse connection)
- Exposes `fetchMarkets()`, `fetchOHLCV()` methods
- Maps PMXT data → Pythia `Market` type
- Includes graceful fallback to mock data on failure

```
Key mapping:
  PMXT Event.title       → Market.question
  PMXT Outcome.yes.price → Market.probability
  PMXT Market.volume     → Market.volume24h
  PMXT Market.liquidity  → Market.liquidity
  PMXT Market.endDate    → Market.endDate
  PMXT exchange name     → Market.source ('polymarket' | 'kalshi')
  PMXT Market.slug/url   → Market.sourceUrl
  OHLCV close prices[]   → Market.probabilityHistory
```

Category mapping (PMXT tags → Pythia categories):
- Fed, rates, FOMC, recession, S&P → `fed`
- Tariff, trade, China sanctions → `tariffs`
- Bitcoin, ETH, crypto, DeFi → `crypto`
- Ukraine, Taiwan, war, ceasefire, AI regulation → `geopolitical`
- Defense, military, budget → `defense`

**Trending detection**: Mark markets with >5% 24h probability change or top 20% by volume as trending.

### Step 2: Update Markets API route

**File**: `pythia-demo/app/api/markets/route.ts`

Replace mock data with PMXT calls:
1. Call `pmxtService.fetchMarkets()` with category/sort/source filters
2. For each market, fetch OHLCV data for probability history (cache aggressively — 5min TTL)
3. Attach signal data from existing `marketSignals` map (keep signal mock data for now until Python backend integration)
4. Fallback: if PMXT fails, return existing mock data with a `dataSource: 'mock'` flag

**Caching strategy**:
- Market list: 60-second in-memory cache (matches frontend 30s poll — always fresh enough)
- OHLCV history: 5-minute cache per market (historical data doesn't change fast)
- Use simple `Map<string, { data, expiry }>` — no external cache dependency

### Step 3: Update Signals API routes

**Files**: `pythia-demo/app/api/signals/route.ts`, `pythia-demo/app/api/signals/[id]/route.ts`

Keep mock signal data for now (signal detection lives in Python backend). Update signal `sourceUrl` fields to use real PMXT market URLs when available.

Future: Connect to Python FastAPI backend at `/api/v1/signals` and `/api/v1/confluence` for live signal data.

### Step 4: Add environment config

**File**: `pythia-demo/.env.local` (new)

```
# Set to 'live' to use PMXT, 'mock' to use hardcoded data
PYTHIA_DATA_SOURCE=live

# Optional: PMXT sidecar port (default auto)
PMXT_PORT=
```

### Step 5: Update types

**File**: `pythia-demo/types/index.ts`

Add `dataSource?: 'live' | 'mock'` to the API response type so the frontend can show a badge indicating live vs demo data.

### Step 6: Update package.json

**File**: `pythia-demo/package.json`

Add `pmxtjs` dependency.

---

## Files Modified

| File | Action |
|------|--------|
| `pythia-demo/lib/pmxt.ts` | **New** — PMXT service singleton |
| `pythia-demo/app/api/markets/route.ts` | **Rewrite** — live data from PMXT |
| `pythia-demo/app/api/signals/route.ts` | **Minor** — update sourceUrls |
| `pythia-demo/app/api/signals/[id]/route.ts` | **Minor** — update sourceUrls |
| `pythia-demo/types/index.ts` | **Minor** — add dataSource field |
| `pythia-demo/package.json` | **Minor** — add pmxtjs dep |
| `pythia-demo/.env.local` | **New** — config |

## Existing code to reuse

- `marketSignals` object in `app/api/markets/route.ts` — keep signal mock data, attach to live markets by matching market question/category
- `genHistory()` in `app/api/markets/route.ts` — keep as fallback when OHLCV fetch fails
- All frontend components (`SparklineChart`, `MarketCard`, `SignalAnalysisPanel`, `TrackRecordTooltip`) — unchanged, they consume the same `Market` type
- Category mapping logic in the existing route — extend for PMXT tag normalization

## Verification

1. `cd pythia-demo && npm install` — confirms pmxtjs installs
2. `npm run build` — TypeScript compilation passes
3. `npm run dev` → visit `/markets` — markets load from PMXT (check Network tab for `/api/markets` response)
4. Verify sparkline charts show real OHLCV data (not random)
5. Toggle source filter (All/PM/Kalshi) — confirms filtering works
6. Set `PYTHIA_DATA_SOURCE=mock` in `.env.local` — confirm fallback works
7. Kill network → confirm graceful degradation to mock data
