import { NextRequest, NextResponse } from 'next/server';

/**
 * Proxy to the Python BACE backend.
 *
 * The frontend calls POST /api/attribute with spike data.
 * This route forwards to the Python FastAPI server and returns the result.
 *
 * Backend URL configured via PYTHIA_API_URL env var.
 * Default: http://localhost:8000 (local dev)
 */

// Allow up to 5 minutes for BACE attribution
export const maxDuration = 300;

const BACKEND_URL = process.env.PYTHIA_API_URL || 'http://localhost:8000';

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();

    const res = await fetch(`${BACKEND_URL}/api/attribute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(300_000), // 5 min timeout for depth 2 with serial news fetching
    });

    if (!res.ok) {
      const err = await res.text();
      return NextResponse.json(
        { success: false, error: `Backend returned ${res.status}: ${err}` },
        { status: 502 }
      );
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (err: any) {
    // Distinguish connection errors from other failures
    if (err.cause?.code === 'ECONNREFUSED' || err.message?.includes('fetch failed')) {
      return NextResponse.json(
        { success: false, error: 'Backend not running. Start it with: uvicorn src.api.server:app --port 8000', backend_url: BACKEND_URL },
        { status: 503 }
      );
    }
    if (err.name === 'TimeoutError') {
      return NextResponse.json(
        { success: false, error: 'Attribution timed out (>120s). Try depth 1 for faster results.' },
        { status: 504 }
      );
    }
    return NextResponse.json(
      { success: false, error: err.message },
      { status: 500 }
    );
  }
}
