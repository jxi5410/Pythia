import { NextRequest, NextResponse } from 'next/server';

const CLOB_URL = 'https://clob.polymarket.com';

export async function GET(req: NextRequest) {
  const tokenId = req.nextUrl.searchParams.get('tokenId') || '';
  const interval = req.nextUrl.searchParams.get('interval') || 'max';
  const fidelity = req.nextUrl.searchParams.get('fidelity') || '60'; // minutes per point

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

    return NextResponse.json({ history, count: history.length });
  } catch (err: any) {
    return NextResponse.json({ error: err.message, history: [] }, { status: 500 });
  }
}
