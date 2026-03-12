import { NextRequest, NextResponse } from 'next/server';

const GAMMA_URL = 'https://gamma-api.polymarket.com';

/**
 * Search Polymarket. Handles:
 * 1. Event URLs:  polymarket.com/event/fed-decision-in-march → events API
 * 2. Market URLs: polymarket.com/market/will-trump-win → markets API
 * 3. Direct slug: ?slug=fed-decision-in-march → try events first, then markets
 * 4. Keywords:    ?q=iran hormuz → search events by title, then markets
 */
export async function GET(req: NextRequest) {
  const query = req.nextUrl.searchParams.get('q') || '';
  const slug = req.nextUrl.searchParams.get('slug') || '';

  try {
    let markets: any[] = [];

    if (slug) {
      // Try as event slug first (events contain markets)
      markets = await searchEventBySlug(slug);
      // If no event found, try as market slug
      if (markets.length === 0) {
        markets = await searchMarketBySlug(slug);
      }
    } else if (query) {
      // Keyword search — scan events (which contain markets)
      markets = await searchByKeyword(query);
    } else {
      // No query — return top markets by volume
      markets = await getTopMarkets();
    }

    const results = markets.slice(0, 15).map(normalizeMarket);
    return NextResponse.json({ markets: results });
  } catch (err: any) {
    return NextResponse.json({ error: err.message, markets: [] }, { status: 500 });
  }
}

async function searchEventBySlug(slug: string): Promise<any[]> {
  // Events API supports partial slug matching
  // Try with exact slug first, then without trailing number suffix
  for (const trySlug of [slug, slug.replace(/-\d+$/, '')]) {
    try {
      const res = await fetch(`${GAMMA_URL}/events?slug=${encodeURIComponent(trySlug)}`);
      const events = await res.json();
      if (Array.isArray(events) && events.length > 0) {
        // Return all markets within the event
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
  const words = q.split(/\s+/).filter(w => w.length > 2);
  const found: any[] = [];

  // Search events (most markets are grouped under events)
  try {
    const res = await fetch(
      `${GAMMA_URL}/events?limit=50&active=true&closed=false&order=volume24hr&ascending=false`
    );
    const events = await res.json();
    if (Array.isArray(events)) {
      for (const evt of events) {
        const title = (evt.title || '').toLowerCase();
        const evtSlug = (evt.slug || '').toLowerCase();
        // Check if any search word appears in event title or slug
        const match = words.some(w => title.includes(w) || evtSlug.includes(w));
        if (match) {
          for (const m of evt.markets || []) {
            found.push(m);
          }
        }
      }
    }
  } catch { /* continue */ }

  // If nothing from events, search markets directly
  if (found.length === 0) {
    try {
      const res = await fetch(
        `${GAMMA_URL}/markets?limit=50&active=true&closed=false&order=volume24hr&ascending=false`
      );
      const allMarkets = await res.json();
      if (Array.isArray(allMarkets)) {
        for (const m of allMarkets) {
          const question = (m.question || '').toLowerCase();
          const mSlug = (m.slug || '').toLowerCase();
          if (words.some(w => question.includes(w) || mSlug.includes(w))) {
            found.push(m);
          }
        }
      }
    } catch { /* */ }
  }

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
        // Take the first (highest volume) market from each event
        if (evt.markets?.[0]) {
          markets.push(evt.markets[0]);
        }
      }
    }
    return markets;
  } catch { return []; }
}

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
