import { NextRequest, NextResponse } from 'next/server';

/**
 * Unified price history endpoint.
 *
 * Polymarket: uses CLOB prices-history API
 * Kalshi: uses candlesticks API (requires series_ticker + ticker)
 *
 * Query params:
 *   exchange       — "polymarket" | "kalshi"
 *   tokenId        — Polymarket CLOB token ID (for Polymarket)
 *   ticker         — Kalshi market ticker (for Kalshi)
 *   series_ticker  — Kalshi series ticker (for Kalshi)
 *   interval       — "max" | number of days (default: "max")
 *   fidelity       — minutes per point (default: 60)
 */

const CLOB_URL = 'https://clob.polymarket.com';
const KALSHI_URL = 'https://api.elections.kalshi.com/trade-api/v2';

export async function GET(req: NextRequest) {
  const exchange = req.nextUrl.searchParams.get('exchange') || 'polymarket';
  const interval = req.nextUrl.searchParams.get('interval') || 'max';
  const fidelity = req.nextUrl.searchParams.get('fidelity') || '60';

  if (exchange === 'kalshi') {
    return handleKalshi(req, interval, parseInt(fidelity));
  }
  return handlePolymarket(req, interval, fidelity);
}

// ─── Polymarket ─────────────────────────────────────────────────────

async function handlePolymarket(req: NextRequest, interval: string, fidelity: string) {
  const tokenId = req.nextUrl.searchParams.get('tokenId') || '';
  if (!tokenId) {
    return NextResponse.json({ error: 'tokenId required', history: [] }, { status: 400 });
  }

  try {
    const res = await fetch(
      `${CLOB_URL}/prices-history?market=${encodeURIComponent(tokenId)}&interval=${interval}&fidelity=${fidelity}`,
      { headers: { 'Accept': 'application/json' } }
    );

    if (!res.ok) {
      return NextResponse.json(
        { error: `CLOB API returned ${res.status}`, history: [] },
        { status: 502 }
      );
    }

    const data = await res.json();
    const history = (data?.history || []).map((pt: any) => ({
      t: new Date(pt.t * 1000).toISOString(),
      price: typeof pt.p === 'number' ? pt.p : parseFloat(pt.p) || 0,
    }));

    return NextResponse.json({ history, count: history.length, exchange: 'polymarket' });
  } catch (err: any) {
    return NextResponse.json({ error: err.message, history: [] }, { status: 500 });
  }
}

// ─── Kalshi ─────────────────────────────────────────────────────────

async function handleKalshi(req: NextRequest, interval: string, fidelityMinutes: number) {
  const ticker = req.nextUrl.searchParams.get('ticker') || '';
  const seriesTicker = req.nextUrl.searchParams.get('series_ticker') || '';

  if (!ticker || !seriesTicker) {
    return NextResponse.json(
      { error: 'ticker and series_ticker required for Kalshi', history: [] },
      { status: 400 }
    );
  }

  try {
    const now = Math.floor(Date.now() / 1000);
    // Calculate start based on interval
    let startTs: number;
    if (interval === 'max') {
      startTs = now - 90 * 24 * 3600; // 90 days
    } else {
      const days = parseInt(interval) || 30;
      startTs = now - days * 24 * 3600;
    }

    // Map fidelity to Kalshi period_interval (1, 60, or 1440)
    let periodInterval = 60; // default 1 hour
    if (fidelityMinutes <= 1) periodInterval = 1;
    else if (fidelityMinutes >= 1440) periodInterval = 1440;
    else periodInterval = 60;

    const url = `${KALSHI_URL}/series/${encodeURIComponent(seriesTicker)}/markets/${encodeURIComponent(ticker)}/candlesticks?start_ts=${startTs}&end_ts=${now}&period_interval=${periodInterval}`;

    const res = await fetch(url, {
      headers: { 'Accept': 'application/json' },
      signal: AbortSignal.timeout(15_000),
    });

    if (!res.ok) {
      const errText = await res.text().catch(() => '');
      return NextResponse.json(
        { error: `Kalshi API returned ${res.status}: ${errText.slice(0, 200)}`, history: [] },
        { status: 502 }
      );
    }

    const data = await res.json();
    const candles = data?.candlesticks || [];

    // Convert candlesticks to PricePoint[] format
    const history = candles
      .filter((c: any) => {
        // Skip synthetic candles (null prices)
        const closePrice = c.price?.close_dollars;
        return closePrice != null && closePrice !== '';
      })
      .map((c: any) => {
        const closePrice = parseFloat(c.price?.close_dollars || '0');
        const ts = c.end_period_ts;
        return {
          t: new Date(ts * 1000).toISOString(),
          price: closePrice, // Already 0-1 range (dollars)
        };
      })
      .filter((pt: any) => pt.price > 0 && pt.price <= 1);

    return NextResponse.json({ history, count: history.length, exchange: 'kalshi' });
  } catch (err: any) {
    return NextResponse.json({ error: err.message, history: [] }, { status: 500 });
  }
}
