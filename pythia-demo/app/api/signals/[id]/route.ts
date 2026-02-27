import { NextResponse } from 'next/server';

import { SignalDetail } from '@/types';

// Extended mock data with full signal details
const mockSignalDetails: Record<string, SignalDetail> = {
  '1': {
    id: '1',
    timestamp: new Date(Date.now() - 1000 * 60 * 15).toISOString(),
    event: 'Fed Rate Cut - March FOMC',
    category: 'fed',
    confluenceLayers: 3,
    totalLayers: 8,
    confidenceScore: 0.87,
    historicalHitRate: 0.73,
    assetImpact: [
      { asset: 'TLT', expectedMove: '+2.1%', correlation: 0.89 },
      { asset: 'SPY', expectedMove: '+0.8%', correlation: 0.73 },
      { asset: 'DXY', expectedMove: '-0.5%', correlation: -0.68 },
      { asset: 'XLF', expectedMove: '-0.3%', correlation: -0.54 }
    ],
    edgeWindow: '18hrs',
    layersFired: [
      'Polymarket (5.2% spike in 30min)',
      'Congressional Trading (3 Fed committee members bought TLT)',
      'Twitter Velocity (2.1x normal volume on #Fed)',
    ],
    layersWithLinks: [
      { text: 'Polymarket (5.2% spike in 30min)', url: 'https://polymarket.com/search?q=fed%20rate' },
      { text: 'Congressional Trading (3 Fed committee members bought TLT)', url: 'https://www.quiverquant.com/congresstrading/' },
      { text: 'Twitter Velocity (2.1x normal volume on #Fed)', url: 'https://x.com/search?q=%23Fed&f=live' },
    ],
    severity: 'high' as const,
    historicalPrecedent: [
      {
        date: '2025-12-18',
        outcome: 'Fed cut 25bps as predicted',
        assetMove: 'TLT +2.3% within 24h'
      },
      {
        date: '2025-11-07',
        outcome: 'Fed held but dovish pivot',
        assetMove: 'TLT +1.8% within 24h'
      },
      {
        date: '2025-09-20',
        outcome: 'Fed cut 25bps surprise',
        assetMove: 'TLT +3.1% within 24h'
      }
    ],
    edgeDecayCurve: [
      { time: '0-6hrs', alphaRemaining: 90 },
      { time: '6-12hrs', alphaRemaining: 70 },
      { time: '12-18hrs', alphaRemaining: 40 },
      { time: '18-24hrs', alphaRemaining: 15 },
      { time: '24hrs+', alphaRemaining: 5 }
    ]
  },
  '2': {
    id: '2',
    timestamp: new Date(Date.now() - 1000 * 60 * 45).toISOString(),
    event: 'Bitcoin ETF Net Flows Spike',
    category: 'crypto',
    confluenceLayers: 2,
    totalLayers: 8,
    confidenceScore: 0.65,
    historicalHitRate: 0.68,
    assetImpact: [
      { asset: 'BTC', expectedMove: '+3.2%', correlation: 0.92 },
      { asset: 'ETH', expectedMove: '+2.8%', correlation: 0.85 },
      { asset: 'COIN', expectedMove: '+4.1%', correlation: 0.88 }
    ],
    edgeWindow: '6hrs',
    layersFired: [
      'Polymarket (Bitcoin $100K March probability +8%)',
      'Crypto On-chain (Whale accumulation detected)'
    ],
    layersWithLinks: [
      { text: 'Polymarket (Bitcoin $100K March probability +8%)', url: 'https://polymarket.com/search?q=bitcoin%20100k' },
      { text: 'Crypto On-chain (Whale accumulation detected)', url: 'https://www.blockchain.com/explorer/assets/btc' },
    ],
    severity: 'medium' as const,
    historicalPrecedent: [
      {
        date: '2026-02-10',
        outcome: 'ETF inflows sustained for 3 days',
        assetMove: 'BTC +5.7% over 72h'
      },
      {
        date: '2026-01-15',
        outcome: 'ETF inflows preceded rally',
        assetMove: 'BTC +4.2% within 48h'
      }
    ],
    edgeDecayCurve: [
      { time: '0-3hrs', alphaRemaining: 85 },
      { time: '3-6hrs', alphaRemaining: 55 },
      { time: '6-12hrs', alphaRemaining: 25 },
      { time: '12hrs+', alphaRemaining: 10 }
    ]
  },
  '3': {
    id: '3',
    timestamp: new Date(Date.now() - 1000 * 60 * 120).toISOString(),
    event: 'China Tariff Escalation Probability',
    category: 'tariffs',
    confluenceLayers: 4,
    totalLayers: 8,
    confidenceScore: 0.91,
    historicalHitRate: 0.81,
    assetImpact: [
      { asset: 'XLI', expectedMove: '-1.5%', correlation: -0.76 },
      { asset: 'FXI', expectedMove: '-2.3%', correlation: -0.82 },
      { asset: 'USDCNY', expectedMove: '+0.4%', correlation: 0.71 },
      { asset: 'SPY', expectedMove: '-0.6%', correlation: -0.58 }
    ],
    edgeWindow: '24hrs',
    layersFired: [
      'Polymarket (Tariff announcement probability +12%)',
      'Twitter Velocity (China trade mentions 3.5x normal)',
      'China Signals (PBOC statement + Weibo sentiment shift)',
      'Equities Correlation (XLI/FXI negative divergence)'
    ],
    layersWithLinks: [
      { text: 'Polymarket (Tariff announcement probability +12%)', url: 'https://polymarket.com/search?q=china%20tariff' },
      { text: 'Twitter Velocity (China trade mentions 3.5x normal)', url: 'https://x.com/search?q=china%20tariff&f=live' },
      { text: 'China Signals (PBOC statement + Weibo sentiment shift)', url: 'http://www.pbc.gov.cn/en/' },
      { text: 'Equities Correlation (XLI/FXI negative divergence)', url: 'https://finance.yahoo.com/quote/XLI/' },
    ],
    severity: 'critical' as const,
    historicalPrecedent: [
      {
        date: '2025-08-15',
        outcome: 'Tariff announcement within 48h',
        assetMove: 'XLI -2.1%, FXI -3.4% within 72h'
      },
      {
        date: '2025-06-22',
        outcome: 'Tariff rumors confirmed',
        assetMove: 'XLI -1.8%, FXI -2.9% within 48h'
      },
      {
        date: '2025-04-10',
        outcome: 'Trade negotiations broke down',
        assetMove: 'XLI -1.3%, FXI -2.6% within 24h'
      }
    ],
    edgeDecayCurve: [
      { time: '0-12hrs', alphaRemaining: 92 },
      { time: '12-24hrs', alphaRemaining: 68 },
      { time: '24-36hrs', alphaRemaining: 35 },
      { time: '36-48hrs', alphaRemaining: 12 },
      { time: '48hrs+', alphaRemaining: 3 }
    ]
  }
};

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const signal = mockSignalDetails[id];

  if (!signal) {
    return NextResponse.json(
      { error: 'Signal not found' },
      { status: 404 }
    );
  }

  return NextResponse.json(signal);
}
