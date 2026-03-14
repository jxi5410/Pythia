export type RunStatus = 'idle' | 'created' | 'running' | 'completed' | 'failed' | 'error';
export type RunErrorSource = 'backend' | 'client' | null;

export interface RunErrorState {
  runStatus: RunStatus;
  runError: string | null;
  runErrorSource: RunErrorSource;
  isRunning: boolean;
}

export function mapBackendStatus(backendStatus: string): RunStatus {
  switch (backendStatus) {
    case 'created':
    case 'pending':
      return 'created';
    case 'running':
    case 'market_snapshot_complete':
    case 'attribution_started':
    case 'attribution_streaming':
    case 'scenario_clustering_complete':
    case 'graph_persisted':
      return 'running';
    case 'completed':
    case 'interrogation_ready':
    case 'partial_complete':
      return 'completed';
    case 'failed':
    case 'failed_terminal':
    case 'failed_retryable':
    case 'error':
    case 'cancelled':
      return 'failed';
    default:
      return 'running';
  }
}

export function isBackendStatusTerminal(backendStatus: string): boolean {
  switch (backendStatus) {
    case 'completed':
    case 'interrogation_ready':
    case 'partial_complete':
    case 'failed':
    case 'failed_terminal':
    case 'failed_retryable':
    case 'error':
    case 'cancelled':
      return true;
    default:
      return false;
  }
}

export function isBackendStatusStreamable(backendStatus: string): boolean {
  switch (backendStatus) {
    case 'created':
    case 'pending':
    case 'running':
    case 'market_snapshot_complete':
    case 'attribution_started':
    case 'attribution_streaming':
    case 'scenario_clustering_complete':
    case 'graph_persisted':
      return true;
    default:
      return false;
  }
}

export function isTerminalReplayableStatus(backendStatus: string): boolean {
  return isBackendStatusTerminal(backendStatus);
}

export function applyClientRunError<T extends RunErrorState>(state: T, message: string): T {
  return {
    ...state,
    runStatus: 'error',
    runError: message,
    runErrorSource: 'client',
    isRunning: false,
  };
}

export function applyBackendRunFailure<T extends RunErrorState>(state: T, message: string): T {
  return {
    ...state,
    runStatus: 'failed',
    runError: message,
    runErrorSource: 'backend',
    isRunning: false,
  };
}

export function applyBackendHydratedStatus<T extends RunErrorState>(
  state: T,
  mappedStatus: RunStatus,
  persistedError: string | null,
): T {
  if (mappedStatus === 'failed') {
    return {
      ...state,
      runStatus: 'failed',
      runError: persistedError,
      runErrorSource: 'backend',
      isRunning: false,
    };
  }

  if (mappedStatus === 'completed') {
    return {
      ...state,
      runStatus: 'completed',
      runError: null,
      runErrorSource: null,
      isRunning: false,
    };
  }

  return {
    ...state,
    runStatus: mappedStatus,
    runError: null,
    runErrorSource: null,
  };
}

export function shouldTreatAsIntentionalAbort(err: unknown, aborted: boolean): boolean {
  return aborted || (err instanceof Error && err.name === 'AbortError');
}
