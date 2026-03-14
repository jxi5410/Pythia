'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useRunStore, C, mono, serif } from '@/lib/run-store';
import BACEGraphAnimation from '@/components/BACEGraphAnimation';
import { formatSpikeTimestamp } from '@/lib/run-presentation';

export default function RunAttributionPage() {
  const router = useRouter();
  const { run } = useRunStore();
  const [elapsedSec, setElapsedSec] = useState(0);
  const elapsedRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Elapsed timer while running
  useEffect(() => {
    if (run.isRunning && !elapsedRef.current) {
      const start = Date.now();
      elapsedRef.current = setInterval(() => {
        setElapsedSec(Math.floor((Date.now() - start) / 1000));
      }, 1000);
    }
    if (!run.isRunning && elapsedRef.current) {
      clearInterval(elapsedRef.current);
      elapsedRef.current = null;
    }
    return () => { if (elapsedRef.current) clearInterval(elapsedRef.current); };
  }, [run.isRunning]);

  const spike = run.selectedSpike;
  const market = run.selectedMarket;
  const showContinue = Boolean(run.attribution && !run.isRunning);
  const failureMessage = run.runErrorSource === 'backend'
    ? (run.runError || 'Attribution failed.')
    : (run.runError || 'Unable to reach the run stream right now.');

  return (
    <div style={{ minHeight: 'calc(100vh - 90px)', background: C.bg, fontFamily: serif, color: C.dark }}>
      <div style={{ maxWidth: 900, margin: '0 auto', padding: '40px 24px' }}>
        {/* Market context */}
        {market && (
          <div style={{ fontFamily: serif, fontSize: 20, fontWeight: 700, marginBottom: 4 }}>
            {market.question}
          </div>
        )}
        <div style={{ fontFamily: mono, fontSize: 11, color: C.muted, marginBottom: 24 }}>
          {spike && (
            <>
              <span style={{ color: spike.direction === 'up' ? C.accent : C.info, fontWeight: 700, fontSize: 14 }}>
                {spike.direction === 'up' ? '+' : '-'}{(spike.magnitude * 100).toFixed(1)}%
              </span>
              {' '}at {formatSpikeTimestamp(spike.timestamp)}
              {' \u00B7 '}
            </>
          )}
          {run.isLive ? <span style={{ color: C.yes }}>&#x25CF; Live</span> : run.isRunning ? <span style={{ color: C.accent }}>&#x25CF; Running BACE depth 2 &#x2014; {elapsedSec}s</span> : <span style={{ color: C.muted }}>&#x25CF; Simulated</span>}
        </div>

        {(run.runStatus === 'error' || run.runStatus === 'failed') && (
          <div style={{ padding: '12px 16px', background: '#fdf0ed', borderRadius: 6, fontFamily: mono, fontSize: 12, color: C.accent, marginBottom: 16 }}>
            {failureMessage}
          </div>
        )}

        {/* BACE Graph Animation */}
        <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, padding: '20px 24px' }}>
          <BACEGraphAnimation baceState={run.baceState} graphState={run.graphState} />
        </div>

        {/* Continue button when complete */}
        {showContinue && run.runId && (
          <div style={{ textAlign: 'center' as const, padding: '28px 0' }}>
            <div style={{ fontFamily: mono, fontSize: 12, color: C.yes, marginBottom: 12 }}>
              &#x2713; Attribution complete &#x2014; {run.attribution?.scenarios?.length || 0} scenarios identified
            </div>
            <button
              onClick={() => router.push(`/run/${run.runId}/scenarios`)}
              style={{
                padding: '14px 40px', borderRadius: 6, border: 'none',
                background: C.dark, color: C.bg, fontFamily: mono,
                fontSize: 14, fontWeight: 600, cursor: 'pointer',
                transition: 'all 0.2s',
              }}
            >
              View Scenarios &#x2192;
            </button>
            <div style={{ fontFamily: mono, fontSize: 10, color: C.muted, marginTop: 8 }}>
              {run.isLive ? '&#x25CF; Live attribution from backend' : '&#x26A0; Simulated &#x2014; backend not connected'}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
