'use client';

import { useEffect, useRef, useCallback, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useRunStore, C, mono, serif } from '@/lib/run-store';
import { runBACEStream } from '@/lib/bace-runner';
import BACEGraphAnimation from '@/components/BACEGraphAnimation';

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
      } catch (err: any) {
        const msg = err?.message || 'Unknown error';
        console.error('[Pythia] BACE attribution failed:', msg);
        setError(`Attribution failed: ${msg}`);
        setRun({ isRunning: false, isLive: false });
      }
    })();

    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [started, run.selectedSpike, run.selectedMarket, run.attribution]);

  // Show continue button when complete — no forced auto-navigate
  const [showContinue, setShowContinue] = useState(false);
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
          {' · '}{run.isLive ? <span style={{ color: C.yes }}>● Live</span> : run.isRunning ? <span style={{ color: C.accent }}>● Running BACE depth 2 — {elapsedSec}s</span> : <span style={{ color: C.muted }}>● Simulated</span>}
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
