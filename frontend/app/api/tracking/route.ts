import { NextResponse } from 'next/server';
import { spawnSync } from 'child_process';
import path from 'path';

export const runtime = 'nodejs';

const PYTHON_SCRIPT = `
import sqlite3, json, os, sys
tracking_dir = sys.argv[1]
db = os.path.join(tracking_dir, 'signals.db')
if not os.path.exists(db):
    print(json.dumps({'signals':[],'moves':[],'stats':{}}))
    raise SystemExit(0)
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row

signals = [dict(r) for r in conn.execute('SELECT * FROM signals ORDER BY timestamp DESC').fetchall()]
moves = [dict(r) for r in conn.execute('SELECT * FROM predicted_moves ORDER BY signal_id').fetchall()]

total = len(signals)
pending = sum(1 for s in signals if s['status']=='pending')
resolved = sum(1 for s in signals if s['status']=='resolved')
hits = sum(1 for m in moves if m['direction_hit']==1)
misses = sum(1 for m in moves if m['direction_hit']==0)
hit_rate = (hits/(hits+misses)*100) if hits+misses>0 else None
avg_err_rows = [m['magnitude_error'] for m in moves if m['magnitude_error'] is not None]
avg_err = sum(avg_err_rows)/len(avg_err_rows) if avg_err_rows else None

print(json.dumps({
    'signals': signals,
    'moves': moves,
    'stats': {
        'total': total, 'pending': pending, 'resolved': resolved,
        'hits': hits, 'misses': misses, 'hitRate': hit_rate,
        'avgMagnitudeError': avg_err,
        'totalMoves': len(moves)
    }
}))
conn.close()
`;

// Read tracking data from SQLite via a Python helper
function getTrackingData() {
  const trackingDir = path.join(process.cwd(), '..', 'tracking');
  try {
    const result = spawnSync(
      'python3',
      ['-c', PYTHON_SCRIPT, trackingDir],
      { encoding: 'utf-8', timeout: 5000, shell: false }
    );
    if (result.status !== 0) {
      throw new Error(result.stderr || 'python tracking command failed');
    }
    return JSON.parse((result.stdout || '').trim() || '{}');
  } catch (e) {
    console.error('Tracking data error:', e);
    return { signals: [], moves: [], stats: { total: 0, pending: 0, resolved: 0 } };
  }
}

export async function GET() {
  const data = getTrackingData();
  return NextResponse.json(data);
}
