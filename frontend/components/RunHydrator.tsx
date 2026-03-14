'use client';

import { useEffect, useState, useRef, ReactNode } from 'react';
import { useRunStore, C, mono, serif } from '@/lib/run-store';

interface RunHydratorProps {
  runId: string;
  children: ReactNode;
}

export default function RunHydrator({ runId, children }: RunHydratorProps) {
  const { run, initRun } = useRunStore();
  const [status, setStatus] = useState<'loading' | 'error' | 'ready'>('loading');
  const [errorMsg, setErrorMsg] = useState('');
  const initCalledRef = useRef<string | null>(null);

  useEffect(() => {
    // Already hydrated for this exact run
    if (run.runId === runId && run.hydrated) {
      setStatus('ready');
      return;
    }

    // Prevent duplicate calls for the same runId
    if (initCalledRef.current === runId) return;
    initCalledRef.current = runId;

    setStatus('loading');
    setErrorMsg('');

    initRun(runId)
      .then(() => setStatus('ready'))
      .catch((err: any) => {
        setErrorMsg(err?.message || 'Failed to load run');
        setStatus('error');
      });
  }, [runId, run.runId, run.hydrated, initRun]);

  // Only render children when store is hydrated for THIS runId
  if (run.runId === runId && run.hydrated && status === 'ready') {
    return <>{children}</>;
  }

  if (status === 'error') {
    return (
      <div style={{
        minHeight: 'calc(100vh - 90px)', background: C.bg,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <div style={{ textAlign: 'center', maxWidth: 400 }}>
          <div style={{ fontSize: 48, marginBottom: 16, opacity: 0.3 }}>&#x26A0;</div>
          <div style={{ fontFamily: serif, fontSize: 18, fontWeight: 600, marginBottom: 8 }}>
            Run not found
          </div>
          <div style={{ fontFamily: mono, fontSize: 12, color: C.muted, marginBottom: 16 }}>
            {errorMsg}
          </div>
          <a href="/" style={{
            fontFamily: mono, fontSize: 12, color: C.info,
            textDecoration: 'underline',
          }}>
            Back to Market Search
          </a>
        </div>
      </div>
    );
  }

  // Loading
  return (
    <div style={{
      minHeight: 'calc(100vh - 90px)', background: C.bg,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <div style={{ textAlign: 'center' }}>
        <div style={{
          width: 24, height: 24,
          border: `2px solid ${C.border}`, borderTopColor: C.accent,
          borderRadius: '50%', animation: 'spin 0.8s linear infinite',
          margin: '0 auto 16px',
        }} />
        <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
        <div style={{ fontFamily: mono, fontSize: 12, color: C.muted }}>
          Loading run {runId.slice(0, 8)}...
        </div>
      </div>
    </div>
  );
}
