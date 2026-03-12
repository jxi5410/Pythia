'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useRunStore, C, mono, serif } from '@/lib/run-store';
import InterrogationChat from '@/components/InterrogationChat';

export default function InterrogationPage() {
  const router = useRouter();
  const { run, setRun } = useRunStore();

  useEffect(() => {
    if (!run.attribution) router.replace('/');
  }, [run.attribution, router]);

  if (!run.attribution) return null;

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
                  {' · '}
                </span>
              )}
              {run.attribution.agentsSpawned} agents · {run.attribution.hypothesesProposed} hypotheses · {run.attribution.elapsed.toFixed(1)}s
              {' · '}<button onClick={() => router.push('/scenarios')} style={{ color: C.info, background: 'none', border: 'none', cursor: 'pointer', fontFamily: mono, fontSize: 11, textDecoration: 'underline' }}>← Back to Scenarios</button>
            </div>
          </div>
        )}

        {/* Chat — full page, always open */}
        <InterrogationChat
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
