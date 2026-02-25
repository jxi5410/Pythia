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
