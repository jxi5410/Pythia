'use client';

import { useRouter } from 'next/navigation';
import { useRunStore, C, mono, serif } from '@/lib/run-store';
import InterrogationChat from '@/components/InterrogationChat';

export default function RunInterrogationPage() {
  const router = useRouter();
  const { run, setRun } = useRunStore();

  if (!run.attribution) {
    return (
      <div style={{ minHeight: 'calc(100vh - 90px)', background: C.bg, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ fontFamily: mono, fontSize: 12, color: C.muted }}>Waiting for attribution...</div>
      </div>
    );
  }

  return (
    <div style={{ minHeight: 'calc(100vh - 90px)', background: C.bg, fontFamily: serif, color: C.dark }}>
      <div style={{ maxWidth: 900, margin: '0 auto', padding: '40px 24px' }}>
        {/* Context header */}
        {run.selectedMarket && (
          <div style={{ marginBottom: 24 }}>
            <div style={{ fontFamily: serif, fontSize: 20, fontWeight: 700, marginBottom: 4 }}>
              {run.selectedMarket.question}
            </div>
            <div style={{ fontFamily: mono, fontSize: 11, color: C.muted }}>
              {run.attribution.scenarios.length > 0 && (
                <span>
                  Top scenario: <span style={{ color: C.dark, fontWeight: 600 }}>
                    {run.attribution.scenarios.find(s => s.tier === 'primary')?.label || 'N/A'}
                  </span>
                  {' \u00B7 '}
                </span>
              )}
              {run.attribution.agentsSpawned} agents &#x00B7; {run.attribution.hypothesesProposed} hypotheses &#x00B7; {run.attribution.elapsed.toFixed(1)}s
              {' \u00B7 '}<button onClick={() => router.push(`/run/${run.runId}/scenarios`)} style={{ color: C.info, background: 'none', border: 'none', cursor: 'pointer', fontFamily: mono, fontSize: 11, textDecoration: 'underline' }}>&#x2190; Back to Scenarios</button>
            </div>
          </div>
        )}

        {/* Chat */}
        <InterrogationChat
          runId={run.runId || ''}
          attributionContext={run.attribution.rawResult || run.attribution}
          marketTitle={run.selectedMarket?.question || ''}
          initialQuestion={run.interrogationQuestion}
          onInitialQuestionConsumed={() => setRun({ interrogationQuestion: undefined })}
          alwaysOpen
        />
      </div>
    </div>
  );
}
