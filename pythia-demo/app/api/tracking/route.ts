import { NextResponse } from 'next/server';
import { execSync } from 'child_process';
import path from 'path';

// Read tracking data from SQLite via a Python helper
function getTrackingData() {
  const trackingDir = path.join(process.cwd(), '..', 'tracking');
  try {
    const result = execSync(
      `python3 -c "
import sqlite3, json, os
db = os.path.join('${trackingDir}', 'signals.db')
if not os.path.exists(db):
    print(json.dumps({'signals':[],'moves':[],'stats':{}}))
    exit()
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
"`,
      { encoding: 'utf-8', timeout: 5000 }
    );
    return JSON.parse(result.trim());
  } catch (e) {
    console.error('Tracking data error:', e);
    return { signals: [], moves: [], stats: { total: 0, pending: 0, resolved: 0 } };
  }
}

export async function GET() {
  const data = getTrackingData();
  return NextResponse.json(data);
}
