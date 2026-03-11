import { NextResponse } from 'next/server';
export const runtime = 'nodejs';

interface PipelineNode {
  id: string; label: string; type: string; layer: number;
  confidence?: number; status?: string; reason?: string;
  url?: string; source?: string; magnitude?: number;
  direction?: 'up' | 'down'; lagHours?: number; pValue?: number; score?: number;
}
interface PipelineEdge {
  source: string; target: string;
  type: 'extracted_from' | 'found_by' | 'survived' | 'eliminated_at' | 'caused_by' | 'propagates_to' | 'correlated_with' | 'validated_by';
}

const TARIFF_PIPELINE: { nodes: PipelineNode[]; edges: PipelineEdge[] } = {
  nodes: [
    { id: 'spike', label: 'China Tariff +7.8%', type: 'spike', layer: 0, magnitude: 0.078, direction: 'up' },
    { id: 'ent-trump', label: '"Trump tariff"', type: 'entity', layer: 1 },
    { id: 'ent-china', label: '"China trade"', type: 'entity', layer: 1 },
    { id: 'ent-tariff', label: '"Section 301"', type: 'entity', layer: 1 },
    { id: 'ent-rare', label: '"rare earth export"', type: 'entity', layer: 1 },
    { id: 'c1', label: 'Trump signs rare earth executive order', type: 'candidate', layer: 2, source: 'Reuters', score: 9, url: 'https://www.reuters.com/world/us/' },
    { id: 'c2', label: 'USTR expands Section 301 investigation', type: 'candidate', layer: 2, source: 'Bloomberg', score: 8 },
    { id: 'c3', label: 'Beijing announces retaliatory tariff package', type: 'candidate', layer: 2, source: 'SCMP', score: 9, url: 'https://www.scmp.com/' },
    { id: 'c4', label: 'Semiconductor export controls tightened', type: 'candidate', layer: 2, source: 'Reuters', score: 7 },
    { id: 'c5', label: 'Apple warns on China supply chain risks', type: 'candidate', layer: 2, source: 'CNBC', score: 5 },
    { id: 'c6', label: 'Phase 2 trade talks collapse in Geneva', type: 'candidate', layer: 2, source: 'FT', score: 8 },
    { id: 'c7', label: 'China GDP growth beats expectations Q4', type: 'candidate', layer: 2, source: 'WSJ', score: 3 },
    { id: 'c8', label: 'Fed minutes suggest rate hold through H1', type: 'candidate', layer: 2, source: 'Reuters', score: 2 },
    { id: 'c9', label: 'Tesla Shanghai factory output hits record', type: 'candidate', layer: 2, source: 'Bloomberg', score: 2 },
    { id: 'c10', label: 'Foxconn diversifies to India', type: 'candidate', layer: 2, source: 'WSJ', score: 4 },
    { id: 'c11', label: 'EU considers aligned China tariff package', type: 'candidate', layer: 2, source: 'Politico', score: 6 },
    { id: 'c12', label: 'Yellen meets Chinese finance minister', type: 'candidate', layer: 2, source: 'NYT', score: 5 },
    { id: 'c13', label: 'MoC spokesperson condemns unilateralism', type: 'candidate', layer: 2, source: 'Xinhua', score: 7 },
    { id: 'c14', label: 'r/worldnews: Trade war escalation imminent', type: 'candidate', layer: 2, source: 'Reddit', score: 4 },
    { id: 'e-c7', label: 'China GDP growth Q4', type: 'eliminated', layer: 3, status: 'eliminated', reason: 'Not causally related — GDP report precedes spike by 3 weeks' },
    { id: 'e-c8', label: 'Fed minutes rate hold', type: 'eliminated', layer: 3, status: 'eliminated', reason: 'Wrong topic — monetary policy, not trade' },
    { id: 'e-c9', label: 'Tesla Shanghai output', type: 'eliminated', layer: 3, status: 'eliminated', reason: 'Tangential — factory output is effect, not cause of tariff change' },
    { id: 'e-c10', label: 'Foxconn diversifies to India', type: 'eliminated', layer: 3, status: 'eliminated', reason: 'Supply chain adaptation, not tariff trigger' },
    { id: 'e-c14', label: 'Reddit speculation', type: 'eliminated', layer: 3, status: 'eliminated', reason: 'No new information — sentiment aggregation, not source' },
    { id: 'e-c5', label: 'Apple supply chain warning', type: 'eliminated', layer: 3, status: 'eliminated', reason: 'Published 6h before window — outside temporal scope' },
    { id: 's-c1', label: 'Trump rare earth executive order', type: 'reasoned', layer: 4, score: 9, source: 'Reuters', confidence: 0.88, status: 'active' },
    { id: 's-c2', label: 'USTR Section 301 expansion', type: 'reasoned', layer: 4, score: 8, source: 'Bloomberg', confidence: 0.63, status: 'active' },
    { id: 's-c3', label: 'Beijing retaliatory tariff package', type: 'reasoned', layer: 4, score: 9, source: 'SCMP', confidence: 0.76, status: 'active' },
    { id: 's-c4', label: 'BIS semiconductor export controls', type: 'reasoned', layer: 4, score: 7, source: 'Reuters', confidence: 0.68, status: 'active' },
    { id: 's-c6', label: 'Phase 2 trade talks collapse', type: 'reasoned', layer: 4, score: 8, source: 'FT', confidence: 0.81, status: 'active' },
    { id: 's-c11', label: 'EU considers aligned tariff', type: 'reasoned', layer: 4, score: 6, source: 'Politico', confidence: 0.42, status: 'unconfirmed' },
    { id: 's-c12', label: 'Yellen meets finance minister', type: 'reasoned', layer: 4, score: 5, source: 'NYT', confidence: 0.35, status: 'unconfirmed' },
    { id: 's-c13', label: 'MoC condemns unilateralism', type: 'reasoned', layer: 4, score: 7, source: 'Xinhua', confidence: 0.51, status: 'unconfirmed' },
    { id: 'val-ci', label: 'CausalImpact: p=0.003', type: 'validated', layer: 5, pValue: 0.003, status: 'active', reason: 'Spike is statistically significant' },
    { id: 'val-dowhy', label: 'DoWhy: refutation passed', type: 'validated', layer: 5, status: 'active', reason: 'Causal effect survives random common cause and placebo tests' },
    { id: 'attr-eo', label: 'Trump executive order on rare earths', type: 'attributor', layer: 6, confidence: 0.88, status: 'active', url: 'https://www.whitehouse.gov/presidential-actions/', reason: 'Direct policy action. Timestamp 2h before spike.' },
    { id: 'attr-301', label: 'USTR Section 301 expanded', type: 'attributor', layer: 6, confidence: 0.63, status: 'active', reason: 'Regulatory escalation reinforces executive order.' },
    { id: 'attr-retaliation', label: 'Beijing retaliatory tariffs', type: 'attributor', layer: 6, confidence: 0.76, status: 'active', url: 'http://english.mofcom.gov.cn/', reason: 'Tit-for-tat escalation. Published 45min after EO.' },
    { id: 'attr-collapse', label: 'Phase 2 talks collapse', type: 'attributor', layer: 6, confidence: 0.81, status: 'active', reason: 'Diplomatic failure removes de-escalation pathway.' },
    { id: 'attr-semi', label: 'BIS semiconductor controls', type: 'attributor', layer: 6, confidence: 0.68, status: 'unconfirmed', reason: 'Reinforcing signal — sector-specific' },
    { id: 'fwd-xli', label: 'XLI (Industrials) ↓', type: 'forward_signal', layer: 7, confidence: 0.72, status: 'predicted', direction: 'down', magnitude: 0.015, lagHours: 4 },
    { id: 'fwd-fxi', label: 'FXI (China ETF) ↓', type: 'forward_signal', layer: 7, confidence: 0.78, status: 'predicted', direction: 'down', magnitude: 0.023, lagHours: 2 },
    { id: 'fwd-usdcny', label: 'USD/CNY ↑', type: 'forward_signal', layer: 7, confidence: 0.61, status: 'predicted', direction: 'up', magnitude: 0.004, lagHours: 6 },
    { id: 'corr-recession', label: 'Recession prob +2.1%', type: 'correlated', layer: 7, confidence: 0.38, status: 'observed', direction: 'up', magnitude: 0.021 },
  ],
  edges: [
    { source: 'spike', target: 'ent-trump', type: 'extracted_from' },
    { source: 'spike', target: 'ent-china', type: 'extracted_from' },
    { source: 'spike', target: 'ent-tariff', type: 'extracted_from' },
    { source: 'spike', target: 'ent-rare', type: 'extracted_from' },
    { source: 'ent-trump', target: 'c1', type: 'found_by' },
    { source: 'ent-tariff', target: 'c2', type: 'found_by' },
    { source: 'ent-china', target: 'c3', type: 'found_by' },
    { source: 'ent-rare', target: 'c4', type: 'found_by' },
    { source: 'ent-china', target: 'c5', type: 'found_by' },
    { source: 'ent-china', target: 'c6', type: 'found_by' },
    { source: 'ent-china', target: 'c7', type: 'found_by' },
    { source: 'ent-trump', target: 'c8', type: 'found_by' },
    { source: 'ent-china', target: 'c9', type: 'found_by' },
    { source: 'ent-china', target: 'c10', type: 'found_by' },
    { source: 'ent-tariff', target: 'c11', type: 'found_by' },
    { source: 'ent-china', target: 'c12', type: 'found_by' },
    { source: 'ent-china', target: 'c13', type: 'found_by' },
    { source: 'ent-trump', target: 'c14', type: 'found_by' },
    { source: 'c7', target: 'e-c7', type: 'eliminated_at' },
    { source: 'c8', target: 'e-c8', type: 'eliminated_at' },
    { source: 'c9', target: 'e-c9', type: 'eliminated_at' },
    { source: 'c10', target: 'e-c10', type: 'eliminated_at' },
    { source: 'c14', target: 'e-c14', type: 'eliminated_at' },
    { source: 'c5', target: 'e-c5', type: 'eliminated_at' },
    { source: 'c1', target: 's-c1', type: 'survived' },
    { source: 'c2', target: 's-c2', type: 'survived' },
    { source: 'c3', target: 's-c3', type: 'survived' },
    { source: 'c4', target: 's-c4', type: 'survived' },
    { source: 'c6', target: 's-c6', type: 'survived' },
    { source: 'c11', target: 's-c11', type: 'survived' },
    { source: 'c12', target: 's-c12', type: 'survived' },
    { source: 'c13', target: 's-c13', type: 'survived' },
    { source: 's-c1', target: 'val-ci', type: 'validated_by' },
    { source: 's-c3', target: 'val-ci', type: 'validated_by' },
    { source: 's-c6', target: 'val-dowhy', type: 'validated_by' },
    { source: 's-c1', target: 'attr-eo', type: 'survived' },
    { source: 's-c2', target: 'attr-301', type: 'survived' },
    { source: 's-c3', target: 'attr-retaliation', type: 'survived' },
    { source: 's-c6', target: 'attr-collapse', type: 'survived' },
    { source: 's-c4', target: 'attr-semi', type: 'survived' },
    { source: 'attr-eo', target: 'fwd-xli', type: 'propagates_to' },
    { source: 'attr-retaliation', target: 'fwd-fxi', type: 'propagates_to' },
    { source: 'attr-eo', target: 'fwd-usdcny', type: 'propagates_to' },
    { source: 'attr-eo', target: 'corr-recession', type: 'correlated_with' },
  ],
};

const FED_PIPELINE: { nodes: PipelineNode[]; edges: PipelineEdge[] } = {
  nodes: [
    { id: 'spike', label: 'Fed Rate Cut +5.2%', type: 'spike', layer: 0, magnitude: 0.052, direction: 'up' },
    { id: 'ent-fed', label: '"Federal Reserve"', type: 'entity', layer: 1 },
    { id: 'ent-rate', label: '"rate cut March"', type: 'entity', layer: 1 },
    { id: 'ent-fomc', label: '"FOMC minutes"', type: 'entity', layer: 1 },
    { id: 'c1', label: 'FOMC minutes show dovish consensus', type: 'candidate', layer: 2, source: 'Reuters', score: 9 },
    { id: 'c2', label: 'PCE inflation undershoots at 2.1%', type: 'candidate', layer: 2, source: 'BLS', score: 8 },
    { id: 'c3', label: 'Waller: "data supports easing"', type: 'candidate', layer: 2, source: 'Fed.gov', score: 7 },
    { id: 'c4', label: 'Jobs report: NFP misses by 80K', type: 'candidate', layer: 2, source: 'BLS', score: 7 },
    { id: 'c5', label: 'ECB signals April cut — Lagarde', type: 'candidate', layer: 2, source: 'FT', score: 4 },
    { id: 'c6', label: 'Treasury auction sees strong demand', type: 'candidate', layer: 2, source: 'Reuters', score: 3 },
    { id: 'c7', label: 'Oil drops 4% on OPEC supply deal', type: 'candidate', layer: 2, source: 'Bloomberg', score: 2 },
    { id: 'e-c5', label: 'ECB Lagarde April cut', type: 'eliminated', layer: 3, status: 'eliminated', reason: 'ECB policy, not Fed — different central bank' },
    { id: 'e-c6', label: 'Treasury auction demand', type: 'eliminated', layer: 3, status: 'eliminated', reason: 'Effect of rate expectations, not cause' },
    { id: 'e-c7', label: 'Oil drops OPEC', type: 'eliminated', layer: 3, status: 'eliminated', reason: 'Energy market, no direct Fed link in this window' },
    { id: 's-c1', label: 'FOMC dovish consensus', type: 'reasoned', layer: 4, confidence: 0.82, status: 'active', source: 'Reuters' },
    { id: 's-c2', label: 'PCE inflation undershoots', type: 'reasoned', layer: 4, confidence: 0.71, status: 'active', source: 'BLS' },
    { id: 's-c3', label: 'Waller dovish speech', type: 'reasoned', layer: 4, confidence: 0.59, status: 'unconfirmed', source: 'Fed.gov' },
    { id: 's-c4', label: 'NFP misses by 80K', type: 'reasoned', layer: 4, confidence: 0.74, status: 'active', source: 'BLS' },
    { id: 'val-ci', label: 'CausalImpact: p=0.008', type: 'validated', layer: 5, pValue: 0.008, status: 'active' },
    { id: 'attr-fomc', label: 'FOMC minutes leaked dovish tone', type: 'attributor', layer: 6, confidence: 0.82, status: 'active', url: 'https://www.reuters.com/markets/us/fed-minutes/' },
    { id: 'attr-pce', label: 'PCE inflation undershoots', type: 'attributor', layer: 6, confidence: 0.71, status: 'active' },
    { id: 'attr-nfp', label: 'NFP misses by 80K', type: 'attributor', layer: 6, confidence: 0.74, status: 'active' },
    { id: 'attr-waller', label: 'Waller hints at March cut', type: 'attributor', layer: 6, confidence: 0.59, status: 'unconfirmed' },
    { id: 'fwd-tlt', label: 'TLT ↑', type: 'forward_signal', layer: 7, confidence: 0.68, status: 'predicted', direction: 'up', magnitude: 0.021, lagHours: 6 },
    { id: 'fwd-dxy', label: 'DXY ↓', type: 'forward_signal', layer: 7, confidence: 0.54, status: 'predicted', direction: 'down', magnitude: 0.005, lagHours: 12 },
    { id: 'corr-btc', label: 'BTC +3.1%', type: 'correlated', layer: 7, confidence: 0.45, status: 'observed', direction: 'up', magnitude: 0.031 },
  ],
  edges: [
    { source: 'spike', target: 'ent-fed', type: 'extracted_from' },
    { source: 'spike', target: 'ent-rate', type: 'extracted_from' },
    { source: 'spike', target: 'ent-fomc', type: 'extracted_from' },
    { source: 'ent-fomc', target: 'c1', type: 'found_by' },
    { source: 'ent-rate', target: 'c2', type: 'found_by' },
    { source: 'ent-fed', target: 'c3', type: 'found_by' },
    { source: 'ent-rate', target: 'c4', type: 'found_by' },
    { source: 'ent-rate', target: 'c5', type: 'found_by' },
    { source: 'ent-fed', target: 'c6', type: 'found_by' },
    { source: 'ent-fed', target: 'c7', type: 'found_by' },
    { source: 'c5', target: 'e-c5', type: 'eliminated_at' },
    { source: 'c6', target: 'e-c6', type: 'eliminated_at' },
    { source: 'c7', target: 'e-c7', type: 'eliminated_at' },
    { source: 'c1', target: 's-c1', type: 'survived' },
    { source: 'c2', target: 's-c2', type: 'survived' },
    { source: 'c3', target: 's-c3', type: 'survived' },
    { source: 'c4', target: 's-c4', type: 'survived' },
    { source: 's-c1', target: 'val-ci', type: 'validated_by' },
    { source: 's-c1', target: 'attr-fomc', type: 'survived' },
    { source: 's-c2', target: 'attr-pce', type: 'survived' },
    { source: 's-c4', target: 'attr-nfp', type: 'survived' },
    { source: 's-c3', target: 'attr-waller', type: 'survived' },
    { source: 'attr-fomc', target: 'fwd-tlt', type: 'propagates_to' },
    { source: 'attr-pce', target: 'fwd-dxy', type: 'propagates_to' },
    { source: 'attr-fomc', target: 'corr-btc', type: 'correlated_with' },
  ],
};

function defaultPipeline(marketId: string) {
  return {
    nodes: [
      { id: 'spike', label: 'Price spike detected', type: 'spike', layer: 0, magnitude: 0.05, direction: 'up' as const },
      { id: 'ent-1', label: '"market keywords"', type: 'entity', layer: 1 },
      { id: 'c1', label: 'Searching news sources…', type: 'candidate', layer: 2, source: 'Pending' },
      { id: 'attr-1', label: 'Insufficient data coverage', type: 'attributor', layer: 6, confidence: 0.0, status: 'unconfirmed' },
    ],
    edges: [
      { source: 'spike', target: 'ent-1', type: 'extracted_from' as const },
      { source: 'ent-1', target: 'c1', type: 'found_by' as const },
      { source: 'c1', target: 'attr-1', type: 'survived' as const },
    ],
  };
}

const pipelines: Record<string, { nodes: PipelineNode[]; edges: PipelineEdge[] }> = {
  'pm-trump-tariff-china': TARIFF_PIPELINE,
  'pm-fed-rate-mar': FED_PIPELINE,
};

const LAYERS = [
  { id: 0, name: 'Spike Detected', description: 'Probability change exceeds threshold' },
  { id: 1, name: 'Entity Extraction', description: 'LLM extracts search terms from market title' },
  { id: 2, name: 'News Retrieval', description: '14 candidates from NewsAPI, Google News, DuckDuckGo, Reddit' },
  { id: 3, name: 'Relevance Filter', description: 'LLM scores relevance + temporal window check (6h before → 1h after)' },
  { id: 4, name: 'Causal Reasoning', description: 'LLM determines causal chain and assigns confidence' },
  { id: 5, name: 'Statistical Validation', description: 'CausalImpact p-value + DoWhy refutation test' },
  { id: 6, name: 'Final Attributors', description: 'Causes that survived all pipeline layers' },
  { id: 7, name: 'Forward Signals', description: 'Predicted downstream market effects via causal graph' },
];

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const marketId = searchParams.get('market');
  if (!marketId) return NextResponse.json({ error: 'market parameter required' }, { status: 400 });
  const pipeline = pipelines[marketId] || defaultPipeline(marketId);
  return NextResponse.json({ marketId, layers: LAYERS, ...pipeline, lastUpdated: new Date().toISOString() });
}
