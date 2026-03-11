import { NextResponse } from 'next/server';

export const runtime = 'nodejs';

// Mock causal graph data per market — maps to attributor_engine + forward_signals data
const mockGraphs: Record<string, { nodes: any[]; edges: any[] }> = {
  'pm-fed-rate-mar': {
    nodes: [
      { id: 'spike-fed', label: 'Fed Rate +5.2%', type: 'spike', magnitude: 0.052, direction: 'up' },
      { id: 'attr-fomc', label: 'FOMC minutes leaked dovish tone', type: 'attributor', confidence: 0.82, status: 'active', url: 'https://www.reuters.com/markets/us/fed-minutes/' },
      { id: 'attr-pce', label: 'PCE inflation undershoots consensus', type: 'attributor', confidence: 0.71, status: 'active', url: 'https://www.bls.gov/pce/' },
      { id: 'attr-waller', label: 'Waller speech hints at March cut', type: 'attributor', confidence: 0.59, status: 'unconfirmed', url: 'https://www.federalreserve.gov/newsevents/speech.htm' },
      { id: 'fwd-tlt', label: 'TLT (20Y Treasury ETF) ↑', type: 'forward_signal', confidence: 0.68, status: 'predicted', direction: 'up', magnitude: 0.021, lagHours: 6 },
      { id: 'fwd-dxy', label: 'DXY weakens', type: 'forward_signal', confidence: 0.54, status: 'predicted', direction: 'down', magnitude: 0.005, lagHours: 12 },
      { id: 'fwd-gold', label: 'Gold spot ↑', type: 'forward_signal', confidence: 0.47, status: 'predicted', direction: 'up', magnitude: 0.012, lagHours: 8 },
      { id: 'corr-btc', label: 'BTC +3.1% (observed)', type: 'correlated', confidence: 0.45, status: 'observed', direction: 'up', magnitude: 0.031 },
    ],
    edges: [
      { source: 'attr-fomc', target: 'spike-fed', type: 'caused_by', strength: 0.82 },
      { source: 'attr-pce', target: 'spike-fed', type: 'caused_by', strength: 0.71 },
      { source: 'attr-waller', target: 'spike-fed', type: 'caused_by', strength: 0.59 },
      { source: 'spike-fed', target: 'fwd-tlt', type: 'propagates_to', strength: 0.68 },
      { source: 'spike-fed', target: 'fwd-dxy', type: 'propagates_to', strength: 0.54 },
      { source: 'spike-fed', target: 'fwd-gold', type: 'propagates_to', strength: 0.47 },
      { source: 'spike-fed', target: 'corr-btc', type: 'correlated_with', strength: 0.45 },
    ],
  },
  'pm-trump-tariff-china': {
    nodes: [
      { id: 'spike-tariff', label: 'China Tariff +7.8%', type: 'spike', magnitude: 0.078, direction: 'up' },
      { id: 'attr-eo', label: 'Trump executive order on rare earths', type: 'attributor', confidence: 0.88, status: 'active', url: 'https://www.whitehouse.gov/presidential-actions/' },
      { id: 'attr-301', label: 'USTR Section 301 expanded', type: 'attributor', confidence: 0.63, status: 'active', url: 'https://ustr.gov/issue-areas/enforcement/section-301-investigations' },
      { id: 'attr-retaliatory', label: 'Beijing retaliatory tariffs', type: 'attributor', confidence: 0.76, status: 'active', url: 'http://english.mofcom.gov.cn/' },
      { id: 'fwd-xli', label: 'XLI (Industrials) ↓', type: 'forward_signal', confidence: 0.72, status: 'predicted', direction: 'down', magnitude: 0.015, lagHours: 4 },
      { id: 'fwd-fxi', label: 'FXI (China ETF) ↓', type: 'forward_signal', confidence: 0.78, status: 'predicted', direction: 'down', magnitude: 0.023, lagHours: 2 },
      { id: 'fwd-usdcny', label: 'USD/CNY ↑', type: 'forward_signal', confidence: 0.61, status: 'predicted', direction: 'up', magnitude: 0.004, lagHours: 6 },
      { id: 'corr-recession', label: 'Recession prob +2.1%', type: 'correlated', confidence: 0.38, status: 'observed', direction: 'up', magnitude: 0.021 },
      { id: 'narr-trade-war', label: 'Trade War Escalation', type: 'narrative' },
    ],
    edges: [
      { source: 'attr-eo', target: 'spike-tariff', type: 'caused_by', strength: 0.88 },
      { source: 'attr-301', target: 'spike-tariff', type: 'caused_by', strength: 0.63 },
      { source: 'attr-retaliatory', target: 'spike-tariff', type: 'caused_by', strength: 0.76 },
      { source: 'spike-tariff', target: 'fwd-xli', type: 'propagates_to', strength: 0.72 },
      { source: 'spike-tariff', target: 'fwd-fxi', type: 'propagates_to', strength: 0.78 },
      { source: 'spike-tariff', target: 'fwd-usdcny', type: 'propagates_to', strength: 0.61 },
      { source: 'spike-tariff', target: 'corr-recession', type: 'correlated_with', strength: 0.38 },
      { source: 'narr-trade-war', target: 'attr-eo', type: 'caused_by', strength: 0.9 },
      { source: 'narr-trade-war', target: 'attr-retaliatory', type: 'caused_by', strength: 0.8 },
    ],
  },
  'kal-btc-100k': {
    nodes: [
      { id: 'spike-btc', label: 'BTC $100K prob +6.1%', type: 'spike', magnitude: 0.061, direction: 'up' },
      { id: 'attr-ibit', label: 'BlackRock IBIT record inflows ($2.1B)', type: 'attributor', confidence: 0.79, status: 'active', url: 'https://www.blackrock.com/us/financial-professionals/products/ibit' },
      { id: 'attr-mtgox', label: 'Mt. Gox creditor distribution deadline', type: 'attributor', confidence: 0.71, status: 'active', url: 'https://www.mtgox.com/' },
      { id: 'attr-tether', label: 'Tether attestation questioned', type: 'attributor', confidence: 0.52, status: 'unconfirmed', url: 'https://tether.to/en/transparency/' },
      { id: 'fwd-eth', label: 'ETH +2.8%', type: 'forward_signal', confidence: 0.73, status: 'predicted', direction: 'up', magnitude: 0.028, lagHours: 3 },
      { id: 'fwd-coin', label: 'COIN (Coinbase) +4.1%', type: 'forward_signal', confidence: 0.65, status: 'predicted', direction: 'up', magnitude: 0.041, lagHours: 4 },
      { id: 'corr-ethstaking', label: 'ETH ETF staking +3.2%', type: 'correlated', confidence: 0.41, status: 'observed', direction: 'up', magnitude: 0.032 },
    ],
    edges: [
      { source: 'attr-ibit', target: 'spike-btc', type: 'caused_by', strength: 0.79 },
      { source: 'attr-mtgox', target: 'spike-btc', type: 'caused_by', strength: 0.71 },
      { source: 'attr-tether', target: 'spike-btc', type: 'caused_by', strength: 0.52 },
      { source: 'spike-btc', target: 'fwd-eth', type: 'propagates_to', strength: 0.73 },
      { source: 'spike-btc', target: 'fwd-coin', type: 'propagates_to', strength: 0.65 },
      { source: 'spike-btc', target: 'corr-ethstaking', type: 'correlated_with', strength: 0.41 },
    ],
  },
};

// Generate a simple default graph for markets without explicit mock data
function defaultGraph(marketId: string): { nodes: any[]; edges: any[] } {
  return {
    nodes: [
      { id: `spike-${marketId}`, label: 'Price spike detected', type: 'spike', magnitude: 0.05, direction: 'up' },
      { id: `attr-${marketId}-1`, label: 'Market sentiment shift', type: 'attributor', confidence: 0.45, status: 'unconfirmed' },
      { id: `attr-${marketId}-2`, label: 'Volume anomaly detected', type: 'attributor', confidence: 0.32, status: 'unconfirmed' },
    ],
    edges: [
      { source: `attr-${marketId}-1`, target: `spike-${marketId}`, type: 'caused_by', strength: 0.45 },
      { source: `attr-${marketId}-2`, target: `spike-${marketId}`, type: 'caused_by', strength: 0.32 },
    ],
  };
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const marketId = searchParams.get('market');

  if (!marketId) {
    return NextResponse.json({ error: 'market parameter required' }, { status: 400 });
  }

  const graph = mockGraphs[marketId] || defaultGraph(marketId);

  return NextResponse.json({
    marketId,
    ...graph,
    lastUpdated: new Date().toISOString(),
  });
}
