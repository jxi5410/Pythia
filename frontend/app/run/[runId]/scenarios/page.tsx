'use client';

import { useRouter } from 'next/navigation';
import { useRunStore, C, mono, serif } from '@/lib/run-store';
import ScenarioPanel from '@/components/ScenarioPanel';
import { formatSpikeTimestamp } from '@/lib/run-presentation';

export default function RunScenariosPage() {
  const router = useRouter();
  const { run, setRun } = useRunStore();

  if (!run.attribution) {
    return (
      <div style={{ minHeight: 'calc(100vh - 90px)', background: C.bg, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ fontFamily: mono, fontSize: 12, color: C.muted }}>Waiting for attribution...</div>
      </div>
    );
  }

  const attr = run.attribution;
  const hasScenarios = attr.scenarios.length > 0;

  const handleAskQuestion = (q: string) => {
    setRun({ interrogationQuestion: q, currentStage: 'interrogation' });
    router.push(`/run/${run.runId}/interrogation`);
  };

  return (
    <div style={{ minHeight: 'calc(100vh - 90px)', background: C.bg, fontFamily: serif, color: C.dark }}>
      <div style={{ maxWidth: 900, margin: '0 auto', padding: '40px 24px' }}>
        {/* Market context */}
        {run.selectedMarket && (
          <div style={{ marginBottom: 8 }}>
            <div style={{ fontFamily: serif, fontSize: 20, fontWeight: 700, marginBottom: 4 }}>
              {run.selectedMarket.question}
            </div>
            {run.selectedSpike && (
              <div style={{ fontFamily: mono, fontSize: 11, color: C.muted, marginBottom: 16 }}>
                Spike: <span style={{ color: run.selectedSpike.direction === 'up' ? C.accent : C.info, fontWeight: 700 }}>
                  {run.selectedSpike.direction === 'up' ? '+' : '-'}{(run.selectedSpike.magnitude * 100).toFixed(1)}%
                </span>
                {' '}at {formatSpikeTimestamp(run.selectedSpike.timestamp)}
                {' \u00B7 '}{run.isLive ? <span style={{ color: C.yes }}>&#x25CF; Live attribution</span> : <span style={{ color: C.accent }}>&#x25CF; Simulated</span>}
              </div>
            )}
          </div>
        )}

        {/* Scenarios */}
        {hasScenarios ? (
          <ScenarioPanel
            attribution={{
              depth: attr.depth,
              agentsSpawned: attr.agentsSpawned,
              hypothesesProposed: attr.hypothesesProposed,
              debateRounds: attr.debateRounds,
              elapsed: attr.elapsed,
              scenarios: attr.scenarios,
              governance: attr.governance,
            }}
            isLive={run.isLive}
            onAskQuestion={handleAskQuestion}
          />
        ) : (
          <LegacyHypotheses attr={attr} isLive={run.isLive} />
        )}

        {/* Continue to interrogation */}
        <div style={{ textAlign: 'center' as const, padding: '24px 0' }}>
          <button
            onClick={() => { setRun({ currentStage: 'interrogation' }); router.push(`/run/${run.runId}/interrogation`); }}
            style={{
              padding: '12px 32px', borderRadius: 6, border: `1px solid ${C.border}`,
              background: C.surface, color: C.dark, fontFamily: mono, fontSize: 13,
              fontWeight: 600, cursor: 'pointer', transition: 'all 0.2s',
              display: 'inline-flex', alignItems: 'center', gap: 8,
            }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.borderColor = C.info; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.borderColor = C.border; }}
          >
            Continue to Interrogation &#x2192;
          </button>
        </div>
      </div>
    </div>
  );
}

// Legacy flat hypothesis list (fallback)
function LegacyHypotheses({ attr, isLive }: { attr: any; isLive: boolean }) {
  return (
    <div style={{ padding: '24px 0' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16, flexWrap: 'wrap' as const }}>
        <span style={{ fontFamily: mono, fontSize: 11, color: C.muted }}>
          Depth {attr.depth} &#x00B7; {attr.agentsSpawned} agents &#x00B7; {attr.hypothesesProposed} hypotheses &#x00B7; {attr.elapsed.toFixed(1)}s
        </span>
        <span style={{ fontFamily: mono, fontSize: 10, color: isLive ? C.yes : C.accent }}>
          {isLive ? '&#x25CF; live' : '&#x26A0; simulated'}
        </span>
      </div>
      {attr.hypotheses.map((h: any, i: number) => {
        const confColor = h.confidence >= 0.7 ? C.yes : h.confidence >= 0.4 ? C.accent : C.muted;
        return (
          <div key={i} style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, marginBottom: 10, padding: '16px 20px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
              <div style={{ width: 44, height: 6, borderRadius: 3, background: C.border, overflow: 'hidden', flexShrink: 0 }}>
                <div style={{ width: `${h.confidence * 100}%`, height: '100%', borderRadius: 3, background: confColor }} />
              </div>
              <span style={{ fontFamily: mono, fontSize: 12, fontWeight: 700, color: confColor }}>{(h.confidence * 100).toFixed(0)}%</span>
              <span style={{ fontFamily: mono, fontSize: 11, fontWeight: 600, color: C.info }}>{h.agent}</span>
            </div>
            <div style={{ fontSize: 14, lineHeight: 1.5, color: C.dark }}>{h.cause}</div>
          </div>
        );
      })}
    </div>
  );
}
