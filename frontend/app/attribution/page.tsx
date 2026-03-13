'use client';

import { useEffect, useRef, useCallback, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useRunStore, C, mono, serif } from '@/lib/run-store';
import { runBACEStream } from '@/lib/bace-runner';
import BACEGraphAnimation from '@/components/BACEGraphAnimation';
import type { BACEState } from '@/components/BACEGraphAnimation';

// Mock generators for fallback
function generateMockBACEStates(question: string): BACEState[] {
  const words = question.replace(/[?.,!]/g, '').split(/\s+/);
  const stop = new Set(['will','the','a','an','by','in','of','to','be','is','are','was','or','and','if','this','that','for','on','at','with','from','not','no','yes']);
  const ents = words.filter(w => w.length > 2 && !stop.has(w.toLowerCase())).filter((w,i,a) => a.indexOf(w) === i).slice(0, 5);
  return [
    { step: 0, entities: [], agentsActive: [], debateLog: ['Classifying market domain…'], counterfactualsTested: 0 },
    { step: 1, entities: [], agentsActive: [], debateLog: ['Extracting causal ontology…'], counterfactualsTested: 0 },
    { step: 2, entities: ents.slice(0,3), agentsActive: [], debateLog: [`Ontology: ${ents.length} entities`, 'Gathering evidence…'], counterfactualsTested: 0 },
    { step: 3, entities: ents, agentsActive: [], debateLog: ['Evidence: 24 candidates', 'Spawning agents…'], counterfactualsTested: 0 },
    { step: 4, entities: ents, agentsActive: ['macro-policy','informed-flow','narrative-sentiment'], debateLog: ['Spawned 9 agents', 'Domain evidence…'], counterfactualsTested: 0 },
    { step: 5, entities: ents, agentsActive: ['macro-policy','informed-flow','narrative-sentiment','cross-market','devils-advocate'], debateLog: ['⟫ Macro Policy Analyst', '  "FOMC sentiment shift…" — 72%', '⟫ Informed Flow Analyst', '  "Whale activity…" — 58%'], counterfactualsTested: 0 },
    { step: 6, entities: ents, agentsActive: ['macro-policy','informed-flow','narrative-sentiment','cross-market','geopolitical','devils-advocate','null-hypothesis'], debateLog: ['Interaction: 3 support, 2 challenges', 'Clustering scenarios…'], counterfactualsTested: 0 },
    { step: 7, entities: ents, agentsActive: ['macro-policy','informed-flow','narrative-sentiment','cross-market','geopolitical','devils-advocate','null-hypothesis'], debateLog: ['Scenarios: 2 primary, 1 dismissed', 'Finalizing…'], counterfactualsTested: 3 },
  ];
}

function generateMockAttribution(spike: any, question: string) {
  return {
    depth: 2, agentsSpawned: 9, hypothesesProposed: 3, debateRounds: 0,
    elapsed: 8.3 + Math.random() * 12,
    hypotheses: [
      { agent: 'Macro Policy Analyst', agentRole: '', cause: 'FOMC-related sentiment shift concurrent with the spike.', reasoning: 'Timing aligns with macro calendar.', confidence: 0.72, confidenceFactors: '', impactSpeed: 'fast', impactSpeedExplain: '', timeToPeak: '2-6h', timeToPeakExplain: '', evidence: [{ source: 'News', title: 'Fed policy analysis', url: null, timestamp: null, timing: 'concurrent' as const }], counterfactual: 'Watch for reversion within 4h.' },
      { agent: 'Informed Flow Analyst', agentRole: '', cause: 'Large directional order — potentially informed flow.', reasoning: 'Volume surge consistent with institutional accumulation.', confidence: 0.58, confidenceFactors: '', impactSpeed: 'immediate', impactSpeedExplain: '', timeToPeak: '1-2h', timeToPeakExplain: '', evidence: [], counterfactual: '' },
      { agent: "Devil's Advocate", agentRole: '', cause: 'Thin orderbook + single large order creating outsized impact.', reasoning: 'Prediction markets have limited liquidity.', confidence: 0.25, confidenceFactors: '', impactSpeed: 'immediate', impactSpeedExplain: '', timeToPeak: 'N/A', timeToPeakExplain: '', evidence: [], counterfactual: '' },
    ],
    scenarios: [
      { id: 'scenario-macro', label: 'Macro / policy-driven (FOMC)', mechanism: 'macro_policy', tier: 'primary' as const, confidence: 0.72, lead_agent: 'Macro Policy Analyst', supporting_agents: ['Macro Policy Analyst', 'Cross-Market Analyst'], challenging_agents: ["Devil's Advocate"], evidence_chain: ['Fed policy analysis', 'Institutional flow'], evidence_urls: [], what_breaks_this: 'Full reversion within 4 hours.', causal_chain: 'FOMC commentary triggered institutional repositioning.', temporal_fit: 'Strong', impact_speed: 'fast', time_to_peak: '2-6h' },
      { id: 'scenario-flow', label: 'Informed flow / whale activity', mechanism: 'informed_flow', tier: 'primary' as const, confidence: 0.58, lead_agent: 'Informed Flow Analyst', supporting_agents: ['Informed Flow Analyst'], challenging_agents: ['Null Hypothesis'], evidence_chain: ['Large directional order', 'Volume 3x baseline'], evidence_urls: [], what_breaks_this: 'No correlated activity in adjacent markets.', causal_chain: 'Sophisticated actor placed directional bet.', temporal_fit: 'Moderate', impact_speed: 'immediate', time_to_peak: '1-2h' },
      { id: 'scenario-noise', label: 'Microstructure (thin book)', mechanism: 'technical', tier: 'dismissed' as const, confidence: 0.25, lead_agent: "Devil's Advocate", supporting_agents: [], challenging_agents: ['Macro Policy Analyst'], evidence_chain: ['Magnitude exceeds 2σ'], evidence_urls: [], what_breaks_this: 'Rejected at p<0.05.', causal_chain: 'Single order on thin book.', temporal_fit: 'Weak', impact_speed: 'immediate', time_to_peak: 'N/A' },
    ],
  };
}

export default function AttributionPage() {
  const router = useRouter();
  const { run, setRun } = useRunStore();
  const [started, setStarted] = useState(false);
  const [error, setError] = useState('');
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Redirect if no spike selected
  useEffect(() => {
    if (!run.selectedSpike || !run.selectedMarket) {
      router.replace('/');
    }
  }, [run.selectedSpike, run.selectedMarket, router]);

  // Auto-start BACE on mount
  useEffect(() => {
    if (started || !run.selectedSpike || !run.selectedMarket) return;
    if (run.attribution) return; // Already have results
    setStarted(true);
    setRun({ isRunning: true });

    (async () => {
      try {
        await runBACEStream(run.selectedMarket!, run.selectedSpike!, {
          onBaceState: (state) => setRun({ baceState: state }),
          onGraphState: (state) => setRun({ graphState: state }),
          onComplete: (attribution) => {
            setRun({
              attribution,
              isRunning: false,
              isLive: true,
              currentStage: 'scenarios',
              completedStages: new Set(['market', 'attribution']),
            });
          },
          onError: (err) => {
            console.log('[Pythia] SSE error:', err);
            throw new Error(err);
          },
        });
      } catch {
        // Fallback to mock
        const question = run.selectedMarket!.question;
        const states = generateMockBACEStates(question);
        let step = 0;
        timerRef.current = setInterval(() => {
          step++;
          if (step < states.length) {
            setRun({ baceState: states[step] });
          } else {
            clearInterval(timerRef.current!);
            const mock = generateMockAttribution(run.selectedSpike, question);
            setRun({
              attribution: mock,
              isRunning: false,
              isLive: false,
              currentStage: 'scenarios',
              completedStages: new Set(['market', 'attribution']),
            });
          }
        }, 900 + Math.random() * 600);
      }
    })();

    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [started, run.selectedSpike, run.selectedMarket, run.attribution]);

  // Show continue button when complete — no forced auto-navigate
  const [showContinue, setShowContinue] = useState(false);
  useEffect(() => {
    if (run.attribution && !run.isRunning) {
      setShowContinue(true);
    }
  }, [run.attribution, run.isRunning]);

  if (!run.selectedSpike || !run.selectedMarket) return null;

  const spike = run.selectedSpike;

  return (
    <div style={{ minHeight: 'calc(100vh - 90px)', background: C.bg, fontFamily: serif, color: C.dark }}>
      <div style={{ maxWidth: 900, margin: '0 auto', padding: '40px 24px' }}>
        {/* Market context */}
        <div style={{ fontFamily: serif, fontSize: 20, fontWeight: 700, marginBottom: 4 }}>
          {run.selectedMarket.question}
        </div>
        <div style={{ fontFamily: mono, fontSize: 11, color: C.muted, marginBottom: 24 }}>
          <span style={{ color: spike.direction === 'up' ? C.accent : C.info, fontWeight: 700, fontSize: 14 }}>
            {spike.direction === 'up' ? '+' : '-'}{(spike.magnitude * 100).toFixed(1)}%
          </span>
          {' '}at {new Date(spike.timestamp).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
          {' · '}{run.isLive ? <span style={{ color: C.yes }}>● Live</span> : run.isRunning ? <span style={{ color: C.accent }}>● Running BACE depth 2</span> : <span style={{ color: C.muted }}>● Simulated</span>}
        </div>

        {error && <div style={{ padding: '12px 16px', background: '#fdf0ed', borderRadius: 6, fontFamily: mono, fontSize: 12, color: C.accent, marginBottom: 16 }}>{error}</div>}

        {/* BACE Graph Animation */}
        <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, padding: '20px 24px' }}>
          <BACEGraphAnimation baceState={run.baceState} graphState={run.graphState} />
        </div>

        {/* Continue button when complete */}
        {showContinue && (
          <div style={{ textAlign: 'center' as const, padding: '28px 0' }}>
            <div style={{ fontFamily: mono, fontSize: 12, color: C.yes, marginBottom: 12 }}>
              ✓ Attribution complete — {run.attribution?.scenarios?.length || 0} scenarios identified
            </div>
            <button
              onClick={() => router.push('/scenarios')}
              style={{
                padding: '14px 40px', borderRadius: 6, border: 'none',
                background: C.dark, color: C.bg, fontFamily: mono,
                fontSize: 14, fontWeight: 600, cursor: 'pointer',
                transition: 'all 0.2s',
              }}
            >
              View Scenarios →
            </button>
            <div style={{ fontFamily: mono, fontSize: 10, color: C.muted, marginTop: 8 }}>
              {run.isLive ? '● Live attribution from backend' : '⚠ Simulated — backend not connected'}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
