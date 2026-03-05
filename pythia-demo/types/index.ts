export interface Signal {
  id: string;
  timestamp: string;
  event: string;
  category: string;
  confluenceLayers: number;
  totalLayers: number;
  confidenceScore: number;
  historicalHitRate: number;
  assetImpact: {
    asset: string;
    expectedMove: string;
    correlation: number;
  }[];
  edgeWindow: string;
  layersFired: string[];
  severity: 'critical' | 'high' | 'medium' | 'low';
  source: 'polymarket' | 'kalshi';
  sourceUrl: string;
}

export interface SignalDetail extends Signal {
  historicalPrecedent: {
    date: string;
    outcome: string;
    assetMove: string;
  }[];
  edgeDecayCurve: {
    time: string;
    alphaRemaining: number;
  }[];
  layersWithLinks?: {
    text: string;
    url: string;
  }[];
}

export interface TrackRecordSummary {
  hitRate: number;
  avgReturn: string;
  sharpeRatio: number;
  totalSignals: number;
  resolved: number;
  wins: number;
  losses: number;
  recentResults: {
    date: string;
    event: string;
    predicted: string;
    actual: string;
    hit: boolean;
  }[];
}

export interface Market {
  id: string;
  question: string;
  category: string;
  probability: number;
  previousProbability: number;
  volume24h: number;
  totalVolume: number;
  liquidity: number;
  endDate: string;
  source: 'polymarket' | 'kalshi';
  sourceUrl: string;
  trending: boolean;
  tags: string[];
  probabilityHistory: number[];
  signal?: Signal & { trackRecord?: TrackRecordSummary };
}

export interface MarketCategory {
  id: string;
  label: string;
  count: number;
  icon: string;
}
