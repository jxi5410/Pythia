import { NextRequest, NextResponse } from 'next/server';

/**
 * Unified market search — queries both Polymarket (Gamma/CLOB) and Kalshi v2 API.
 *
 * Query params:
 *   q        — keyword search
 *   slug     — Polymarket slug lookup
 *   exchange — "polymarket" | "kalshi" | "all" (default: "all")
 */

const GAMMA_URL = 'https://gamma-api.polymarket.com';
const CLOB_URL = 'https://clob.polymarket.com';
const KALSHI_URL = 'https://api.elections.kalshi.com/trade-api/v2';

export async function GET(req: NextRequest) {
  const query = req.nextUrl.searchParams.get('q') || '';
  const slug = req.nextUrl.searchParams.get('slug') || '';
  const exchange = req.nextUrl.searchParams.get('exchange') || 'all';

  try {
    const promises: Promise<any[]>[] = [];

    if (exchange === 'all' || exchange === 'polymarket') {
      promises.push(searchPolymarket(query, slug));
    }
    if ((exchange === 'all' || exchange === 'kalshi') && !slug) {
      // Kalshi doesn't have slug-based lookup
      promises.push(searchKalshi(query));
    }

    const results = await Promise.allSettled(promises);
    let markets: any[] = [];

    for (const r of results) {
      if (r.status === 'fulfilled') {
        markets.push(...r.value);
      }
    }

    // Sort by volume, take top 20
    markets.sort((a: any, b: any) => (b.volume24hr || 0) - (a.volume24hr || 0));
    markets = markets.slice(0, 20);

    // Fetch spike counts in parallel (Polymarket only — Kalshi uses candlesticks)
    const withSpikes = await addSpikeCounts(markets);

    return NextResponse.json({ markets: withSpikes });
  } catch (err: any) {
    return NextResponse.json({ error: err.message, markets: [] }, { status: 500 });
  }
}

// ─── Polymarket Search ──────────────────────────────────────────────

async function searchPolymarket(query: string, slug: string): Promise<any[]> {
  if (slug) {
    let markets = await searchEventBySlug(slug);
    if (markets.length === 0) markets = await searchMarketBySlug(slug);
    return markets.map(normalizePolymarket);
  }
  if (query) {
    return (await searchPolymarketByKeyword(query)).map(normalizePolymarket);
  }
  return (await getTopPolymarkets()).map(normalizePolymarket);
}

async function searchEventBySlug(slug: string): Promise<any[]> {
  for (const trySlug of [slug, slug.replace(/-\d+$/, '')]) {
    try {
      const res = await fetch(`${GAMMA_URL}/events?slug=${encodeURIComponent(trySlug)}`);
      const events = await res.json();
      if (Array.isArray(events) && events.length > 0) {
        return events[0].markets || [];
      }
    } catch { /* try next */ }
  }
  return [];
}

async function searchMarketBySlug(slug: string): Promise<any[]> {
  try {
    const res = await fetch(`${GAMMA_URL}/markets?slug=${encodeURIComponent(slug)}&limit=1`);
    const data = await res.json();
    return Array.isArray(data) ? data : [];
  } catch { return []; }
}

async function searchPolymarketByKeyword(query: string): Promise<any[]> {
  const q = query.toLowerCase().trim();
  const words = q.split(/\s+/).filter(w => w.length > 1);
  if (words.length === 0) return getTopPolymarkets();

  const found: any[] = [];
  const seenSlugs = new Set<string>();
  const addMarket = (m: any) => {
    const s = m.slug || m.id || '';
    if (!seenSlugs.has(s)) { seenSlugs.add(s); found.push(m); }
  };

  const [eventsRes, marketsRes] = await Promise.allSettled([
    fetch(`${GAMMA_URL}/events?limit=100&active=true&closed=false&order=volume24hr&ascending=false`),
    fetch(`${GAMMA_URL}/markets?limit=500&active=true&closed=false&order=volume24hr&ascending=false`),
  ]);

  if (eventsRes.status === 'fulfilled') {
    try {
      const events = await eventsRes.value.json();
      if (Array.isArray(events)) {
        for (const evt of events) {
          const title = (evt.title || '').toLowerCase();
          const evtSlug = (evt.slug || '').toLowerCase();
          if (words.some(w => title.includes(w) || evtSlug.includes(w))) {
            for (const m of evt.markets || []) addMarket(m);
          }
        }
      }
    } catch { /* */ }
  }

  if (marketsRes.status === 'fulfilled') {
    try {
      const allMarkets = await marketsRes.value.json();
      if (Array.isArray(allMarkets)) {
        for (const m of allMarkets) {
          const question = (m.question || '').toLowerCase();
          const mSlug = (m.slug || '').toLowerCase();
          if (words.some(w => question.includes(w) || mSlug.includes(w))) {
            addMarket(m);
          }
        }
      }
    } catch { /* */ }
  }

  found.sort((a: any, b: any) => (b.volume24hr || 0) - (a.volume24hr || 0));
  return found;
}

async function getTopPolymarkets(): Promise<any[]> {
  try {
    const res = await fetch(
      `${GAMMA_URL}/events?limit=10&active=true&closed=false&order=volume24hr&ascending=false`
    );
    const events = await res.json();
    const markets: any[] = [];
    if (Array.isArray(events)) {
      for (const evt of events) {
        if (evt.markets?.[0]) markets.push(evt.markets[0]);
      }
    }
    return markets;
  } catch { return []; }
}

function normalizePolymarket(m: any) {
  let clobTokenIds: string[] = [];
  try {
    clobTokenIds = typeof m.clobTokenIds === 'string'
      ? JSON.parse(m.clobTokenIds) : m.clobTokenIds || [];
  } catch { /* */ }

  let outcomes: string[] = [];
  try {
    outcomes = typeof m.outcomes === 'string'
      ? JSON.parse(m.outcomes) : m.outcomes || ['Yes', 'No'];
  } catch { /* */ }

  let outcomePrices: string[] = [];
  try {
    outcomePrices = typeof m.outcomePrices === 'string'
      ? JSON.parse(m.outcomePrices) : m.outcomePrices || [];
  } catch { /* */ }

  return {
    id: m.id,
    question: m.question,
    slug: m.slug,
    conditionId: m.conditionId,
    clobTokenIds,
    outcomes,
    outcomePrices,
    volume24hr: m.volume24hr || 0,
    volume: m.volumeNum || m.volume || 0,
    endDate: m.endDate,
    image: m.image,
    exchange: 'polymarket' as const,
  };
}

// ─── Kalshi Search ──────────────────────────────────────────────────

async function searchKalshi(query: string): Promise<any[]> {
  try {
    // Kalshi GET /markets with status=open, paginated
    const params = new URLSearchParams({
      status: 'open',
      limit: '200',
    });

    const res = await fetch(`${KALSHI_URL}/markets?${params}`, {
      headers: { 'Accept': 'application/json' },
      signal: AbortSignal.timeout(10_000),
    });

    if (!res.ok) return [];
    const data = await res.json();
    const rawMarkets = data.markets || [];

    if (!query) {
      // No query — return top by volume
      return rawMarkets
        .sort((a: any, b: any) => (b.volume_24h || b.volume || 0) - (a.volume_24h || a.volume || 0))
        .slice(0, 15)
        .map(normalizeKalshi);
    }

    // Keyword filter
    const words = query.toLowerCase().split(/\s+/).filter(w => w.length > 1);
    const matched = rawMarkets.filter((m: any) => {
      const title = (m.title || '').toLowerCase();
      const subtitle = (m.subtitle || '').toLowerCase();
      const ticker = (m.ticker || '').toLowerCase();
      const eventTicker = (m.event_ticker || '').toLowerCase();
      return words.some(w =>
        title.includes(w) || subtitle.includes(w) ||
        ticker.includes(w) || eventTicker.includes(w)
      );
    });

    return matched
      .sort((a: any, b: any) => (b.volume_24h || b.volume || 0) - (a.volume_24h || a.volume || 0))
      .slice(0, 15)
      .map(normalizeKalshi);
  } catch (err) {
    console.error('[Kalshi search]', err);
    return [];
  }
}

function normalizeKalshi(m: any) {
  // Kalshi prices are in cents (0-100); normalize to 0-1
  const yesPrice = (m.yes_bid != null ? m.yes_bid : m.last_price || 50) / 100;
  const volume24h = m.volume_24h || 0;
  const volume = m.volume || 0;

  return {
    id: m.ticker || m.id || '',
    question: m.title || m.subtitle || 'Unknown',
    slug: m.ticker || '',
    conditionId: '',
    clobTokenIds: [], // Kalshi doesn't use CLOB tokens
    outcomes: ['Yes', 'No'],
    outcomePrices: [String(yesPrice), String(1 - yesPrice)],
    volume24hr: volume24h,
    volume: volume,
    endDate: m.close_time || m.expiration_time || '',
    image: '',
    exchange: 'kalshi' as const,
    // Kalshi-specific fields needed for price history
    kalshiTicker: m.ticker || '',
    kalshiEventTicker: m.event_ticker || '',
    kalshiSeriesTicker: m.series_ticker || '',
  };
}

// ─── Spike counting (Polymarket only) ───────────────────────────────

async function countSpikesPolymarket(tokenId: string): Promise<number> {
  try {
    const res = await fetch(
      `${CLOB_URL}/prices-history?market=${encodeURIComponent(tokenId)}&interval=max&fidelity=60`,
      { headers: { 'Accept': 'application/json' } }
    );
    if (!res.ok) return -1;
    const data = await res.json();
    const history = data?.history || [];
    if (history.length < 8) return 0;

    const prices = history.map((pt: any) => typeof pt.p === 'number' ? pt.p : parseFloat(pt.p) || 0);
    const pMin = Math.min(...prices);
    const pMax = Math.max(...prices);
    const range = pMax - pMin;
    const sorted = [...prices].sort((a, b) => a - b);
    const median = sorted[Math.floor(sorted.length / 2)] || 0.5;
    const absThresh = range * 0.15;
    const relThresh = median * 0.10;
    const threshold = Math.max(0.005, Math.min(absThresh, relThresh));
    const win = Math.min(4, Math.floor(prices.length / 10));

    let spikeCount = 0;
    let lastSpikeIdx = -12;
    for (let i = win; i < prices.length; i++) {
      const mag = Math.abs(prices[i] - prices[i - win]);
      if (mag >= threshold && (i - lastSpikeIdx) >= 12) {
        spikeCount++;
        lastSpikeIdx = i;
      }
    }
    return spikeCount;
  } catch {
    return -1;
  }
}

async function countSpikesKalshi(ticker: string, seriesTicker: string): Promise<number> {
  try {
    // Use candlesticks endpoint for Kalshi price history
    const now = Math.floor(Date.now() / 1000);
    const thirtyDaysAgo = now - 30 * 24 * 3600;
    const url = `${KALSHI_URL}/series/${encodeURIComponent(seriesTicker)}/markets/${encodeURIComponent(ticker)}/candlesticks?start_ts=${thirtyDaysAgo}&end_ts=${now}&period_interval=60`;

    const res = await fetch(url, {
      headers: { 'Accept': 'application/json' },
      signal: AbortSignal.timeout(8_000),
    });
    if (!res.ok) return -1;
    const data = await res.json();
    const candles = data?.candlesticks || [];
    if (candles.length < 8) return 0;

    // Extract close prices (in dollars, string like "0.5600")
    const prices = candles.map((c: any) => {
      const p = c.price?.close_dollars || c.price?.mean_dollars || '0.50';
      return parseFloat(p);
    }).filter((p: number) => !isNaN(p) && p > 0);

    if (prices.length < 8) return 0;

    const pMin = Math.min(...prices);
    const pMax = Math.max(...prices);
    const range = pMax - pMin;
    const sorted = [...prices].sort((a, b) => a - b);
    const median = sorted[Math.floor(sorted.length / 2)] || 0.5;
    const absThresh = range * 0.15;
    const relThresh = median * 0.10;
    const threshold = Math.max(0.005, Math.min(absThresh, relThresh));
    const win = Math.min(4, Math.floor(prices.length / 10));

    let spikeCount = 0;
    let lastSpikeIdx = -12;
    for (let i = win; i < prices.length; i++) {
      const mag = Math.abs(prices[i] - prices[i - win]);
      if (mag >= threshold && (i - lastSpikeIdx) >= 12) {
        spikeCount++;
        lastSpikeIdx = i;
      }
    }
    return spikeCount;
  } catch {
    return -1;
  }
}

async function addSpikeCounts(markets: any[]): Promise<any[]> {
  const promises = markets.map(async (m) => {
    if (m.exchange === 'kalshi') {
      if (!m.kalshiTicker || !m.kalshiSeriesTicker) return { ...m, spikeCount: -1 };
      const count = await countSpikesKalshi(m.kalshiTicker, m.kalshiSeriesTicker);
      return { ...m, spikeCount: count };
    } else {
      const tokenId = m.clobTokenIds?.[0];
      if (!tokenId) return { ...m, spikeCount: -1 };
      const count = await countSpikesPolymarket(tokenId);
      return { ...m, spikeCount: count };
    }
  });
  return Promise.all(promises);
}
