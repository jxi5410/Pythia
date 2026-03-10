import { NextResponse } from 'next/server';

import { pmxtService } from '@/lib/pmxt';

export const runtime = 'nodejs';

// Mock data for demo - in production this would fetch from Pythia backend
const mockSignals = [
  {
    id: '1',
    timestamp: new Date(Date.now() - 1000 * 60 * 15).toISOString(), // 15 min ago
    event: 'Fed Rate Cut - March FOMC',
    category: 'fed',
    confluenceLayers: 3,
    totalLayers: 8,
    confidenceScore: 0.87,
    historicalHitRate: 0.73,
    assetImpact: [
      { asset: 'TLT', expectedMove: '+2.1%', correlation: 0.89 },
      { asset: 'SPY', expectedMove: '+0.8%', correlation: 0.73 },
      { asset: 'DXY', expectedMove: '-0.5%', correlation: -0.68 }
    ],
    edgeWindow: '18hrs',
    layersFired: ['Polymarket', 'Congressional', 'Twitter'],
    severity: 'high' as const,
    source: 'polymarket' as const,
    sourceUrl: 'https://polymarket.com/event/fed-rate-decision-march-2026',
  },
  {
    id: '2',
    timestamp: new Date(Date.now() - 1000 * 60 * 45).toISOString(), // 45 min ago
    event: 'Bitcoin ETF Net Flows Spike',
    category: 'crypto',
    confluenceLayers: 2,
    totalLayers: 8,
    confidenceScore: 0.65,
    historicalHitRate: 0.68,
    assetImpact: [
      { asset: 'BTC', expectedMove: '+3.2%', correlation: 0.92 },
      { asset: 'ETH', expectedMove: '+2.8%', correlation: 0.85 }
    ],
    edgeWindow: '6hrs',
    layersFired: ['Polymarket', 'Crypto On-chain'],
    severity: 'medium' as const,
    source: 'kalshi' as const,
    sourceUrl: 'https://kalshi.com/markets/btc/bitcoin-100k',
  },
  {
    id: '3',
    timestamp: new Date(Date.now() - 1000 * 60 * 120).toISOString(), // 2 hrs ago
    event: 'China Tariff Escalation Probability',
    category: 'tariffs',
    confluenceLayers: 4,
    totalLayers: 8,
    confidenceScore: 0.91,
    historicalHitRate: 0.81,
    assetImpact: [
      { asset: 'XLI', expectedMove: '-1.5%', correlation: -0.76 },
      { asset: 'FXI', expectedMove: '-2.3%', correlation: -0.82 },
      { asset: 'USDCNY', expectedMove: '+0.4%', correlation: 0.71 }
    ],
    edgeWindow: '24hrs',
    layersFired: ['Polymarket', 'Twitter', 'China Signals', 'Equities'],
    severity: 'critical' as const,
    source: 'polymarket' as const,
    sourceUrl: 'https://polymarket.com/event/china-tariff-escalation',
  }
];

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const category = searchParams.get('category');

  let filteredSignals = [...mockSignals];
  
  if (category && category !== 'all') {
    filteredSignals = mockSignals.filter(s => s.category === category);
  }

  if ((process.env.PYTHIA_DATA_SOURCE ?? 'live') === 'live') {
    try {
      const hints = await pmxtService.fetchSourceUrlHints();
      filteredSignals = filteredSignals.map((signal) => {
        const key = `${signal.source}:${signal.category}`;
        const hintedUrl = hints[key];
        return hintedUrl ? { ...signal, sourceUrl: hintedUrl } : signal;
      });
    } catch {
      // Keep mock source URLs when PMXT is unavailable.
    }
  }

  // Sort by timestamp desc
  filteredSignals.sort((a, b) => 
    new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
  );

  return NextResponse.json({
    signals: filteredSignals,
    count: filteredSignals.length,
    lastUpdated: new Date().toISOString()
  });
}
