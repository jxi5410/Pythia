import { NextRequest, NextResponse } from 'next/server';

const GAMMA_URL = 'https://gamma-api.polymarket.com';
const CLOB_URL = 'https://clob.polymarket.com';

export async function GET(req: NextRequest) {
  const query = req.nextUrl.searchParams.get('q') || '';
  const slug = req.nextUrl.searchParams.get('slug') || '';

  try {
    let markets: any[] = [];

    if (slug) {
      markets = await searchEventBySlug(slug);
      if (markets.length === 0) markets = await searchMarketBySlug(slug);
    } else if (query) {
      markets = await searchByKeyword(query);
    } else {
      markets = await getTopMarkets();
    }

    // Normalize and limit to 15
    const results = markets.slice(0, 15).map(normalizeMarket);

    // Fetch spike counts in parallel for all results
    const withSpikes = await addSpikeCounts(results);

    return NextResponse.json({ markets: withSpikes });
  } catch (err: any) {
    return NextResponse.json({ error: err.message, markets: [] }, { status: 500 });
  }
}

// ─── Search functions ────────────────────────────────────────────────

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

async function searchByKeyword(query: string): Promise<any[]> {
  const q = query.toLowerCase().trim();
  const words = q.split(/\s+/).filter(w => w.length > 1);
  if (words.length === 0) return getTopMarkets();
  const found: any[] = [];
  const seenSlugs = new Set<string>();

  const addMarket = (m: any) => {
    const s = m.slug || m.id || '';
    if (!seenSlugs.has(s)) { seenSlugs.add(s); found.push(m); }
  };

  // Scan events (100) + markets (500) in parallel
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

async function getTopMarkets(): Promise<any[]> {
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

// ─── Spike counting ──────────────────────────────────────────────────

async function countSpikes(tokenId: string): Promise<number> {
  try {
    const res = await fetch(
      `${CLOB_URL}/prices-history?market=${encodeURIComponent(tokenId)}&interval=max&fidelity=60`,
      { headers: { 'Accept': 'application/json' } }
    );
    if (!res.ok) return -1;
    const data = await res.json();
    const history = data?.history || [];
    if (history.length < 8) return 0;

    // Quick spike detection (same algo as frontend)
    const prices = history.map((pt: any) => typeof pt.p === 'number' ? pt.p : parseFloat(pt.p) || 0);
    const pMin = Math.min(...prices);
    const pMax = Math.max(...prices);
    const range = pMax - pMin;
    const threshold = Math.max(0.02, range * 0.15);
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
    return -1; // fetch failed
  }
}

async function addSpikeCounts(markets: any[]): Promise<any[]> {
  // Fetch spike counts for all markets in parallel
  const promises = markets.map(async (m) => {
    const tokenId = m.clobTokenIds?.[0];
    if (!tokenId) return { ...m, spikeCount: -1 };
    const count = await countSpikes(tokenId);
    return { ...m, spikeCount: count };
  });

  return Promise.all(promises);
}

// ─── Normalize ───────────────────────────────────────────────────────

function normalizeMarket(m: any) {
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
  };
}
