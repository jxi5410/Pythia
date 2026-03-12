import { NextRequest, NextResponse } from 'next/server';

const GAMMA_URL = 'https://gamma-api.polymarket.com';

export async function GET(req: NextRequest) {
  const query = req.nextUrl.searchParams.get('q') || '';
  const slug = req.nextUrl.searchParams.get('slug') || '';

  try {
    let markets: any[] = [];

    if (slug) {
      const res = await fetch(`${GAMMA_URL}/markets?slug=${encodeURIComponent(slug)}&limit=1`);
      const data = await res.json();
      markets = Array.isArray(data) ? data : data?.data || data?.markets || [];
    } else if (query) {
      // Search via events endpoint first (more reliable)
      const res = await fetch(
        `${GAMMA_URL}/events?limit=15&active=true&closed=false&order=volume24hr&ascending=false`
      );
      const events = await res.json();
      const q = query.toLowerCase();
      for (const evt of (Array.isArray(events) ? events : [])) {
        for (const m of evt.markets || []) {
          if (
            m.question?.toLowerCase().includes(q) ||
            m.slug?.toLowerCase().includes(q) ||
            evt.title?.toLowerCase().includes(q)
          ) {
            markets.push(m);
          }
        }
      }
      // Fallback: search top markets directly
      if (markets.length === 0) {
        const res2 = await fetch(
          `${GAMMA_URL}/markets?limit=30&active=true&closed=false&order=volume24hr&ascending=false`
        );
        const allMarkets = await res2.json();
        markets = (Array.isArray(allMarkets) ? allMarkets : []).filter(
          (m: any) =>
            m.question?.toLowerCase().includes(q) ||
            m.slug?.toLowerCase().includes(q)
        );
      }
    } else {
      const res = await fetch(
        `${GAMMA_URL}/markets?limit=10&active=true&closed=false&order=volume24hr&ascending=false`
      );
      markets = await res.json();
      if (!Array.isArray(markets)) markets = [];
    }

    const results = markets.slice(0, 10).map((m: any) => {
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
    });

    return NextResponse.json({ markets: results });
  } catch (err: any) {
    return NextResponse.json({ error: err.message, markets: [] }, { status: 500 });
  }
}
