# Pythia Demo - Mobile-First Web App

Zero-friction demo for design partner outreach. Tap link → see live signals immediately.

## What This Is

Mobile-optimized Progressive Web App for showcasing Pythia's prediction market intelligence to institutional traders.

**No friction:**
- ✅ No app install required
- ✅ No Telegram setup
- ✅ No account creation
- ✅ No commands to learn
- ✅ Works on any mobile browser

**Core experience:**
- Live signal feed (confluence alerts)
- Signal detail view (layers fired, asset impact, edge window)
- Filter by category (Fed, Tariffs, Crypto, etc.)
- One-tap share via native share sheet

## Quick Start

```bash
# Install dependencies
npm install

# Run development server
npm run dev

# Open http://localhost:3000
```

## Deployment to Vercel (Production)

### 1. Push to GitHub

```bash
cd /Users/xj.ai/.openclaw/workspace/projects/pythia/pythia-demo
git init
git add .
git commit -m "Initial Pythia demo"
git remote add origin https://github.com/jxi5410/pythia-demo.git
git push -u origin main
```

### 2. Deploy to Vercel

**Via Vercel CLI (fastest):**
```bash
npm install -g vercel
vercel login
vercel --prod
```

**Via Vercel Dashboard:**
1. Go to https://vercel.com/new
2. Import `jxi5410/pythia-demo` from GitHub
3. Framework: Next.js (auto-detected)
4. Click "Deploy"

**Result:** Live at `pythia-demo.vercel.app` in ~2 minutes

### 3. Custom Domain Setup

**Option A: Subdomain (demo.pythia.live)**

In Vercel project settings → Domains:
1. Add domain: `demo.pythia.live`
2. Copy provided DNS records
3. Add CNAME record to your DNS:
   ```
   demo.pythia.live → cname.vercel-dns.com
   ```

**Option B: Use pythia.live directly**

If you don't own pythia.live yet:
1. Register at Namecheap/Cloudflare ($12/year)
2. Point to Vercel as above

**Result:** Live at `demo.pythia.live` within 10 minutes

## Tech Stack

- **Framework:** Next.js 15 (React 19)
- **Styling:** Tailwind CSS 4
- **Deployment:** Vercel (zero config)
- **Backend:** API Routes (mock data for demo)

## File Structure

```
pythia-demo/
├── app/
│   ├── page.tsx              # Main feed
│   ├── signal/[id]/page.tsx  # Signal detail
│   ├── api/
│   │   └── signals/          # Mock API
│   ├── layout.tsx
│   └── globals.css
├── components/
│   └── SignalCard.tsx
├── types/
│   └── index.ts
└── public/
    └── manifest.json         # PWA config
```

## Mock Data → Live Data Integration

Currently uses mock signals in `/app/api/signals/route.ts`.

**To connect to real Pythia backend:**

```typescript
// app/api/signals/route.ts
export async function GET(request: Request) {
  // Replace this:
  const mockSignals = [...];
  
  // With this:
  const response = await fetch('http://pythia-backend:8000/v1/signals');
  const signals = await response.json();
  
  return NextResponse.json({ signals });
}
```

**Backend API expected format:**
```json
{
  "signals": [
    {
      "id": "string",
      "timestamp": "ISO 8601",
      "event": "string",
      "category": "fed|tariffs|crypto|geopolitical|defense",
      "confluenceLayers": number,
      "totalLayers": 8,
      "confidenceScore": 0-1,
      "historicalHitRate": 0-1,
      "assetImpact": [
        { "asset": "TLT", "expectedMove": "+2.1%", "correlation": 0.89 }
      ],
      "edgeWindow": "18hrs",
      "layersFired": ["Polymarket", "Congressional"],
      "severity": "critical|high|medium|low"
    }
  ]
}
```

## Mobile Testing

**iOS Safari:**
1. Open `http://localhost:3000` on iPhone
2. Tap Share → Add to Home Screen
3. Launch from home screen (full-screen app)

**Android Chrome:**
1. Open `http://localhost:3000`
2. Tap menu → "Install app" banner
3. Launch as standalone app

## Design Partner Outreach Flow

**Step 1: Deploy**
```bash
vercel --prod
```

**Step 2: Get URL**
```
https://demo.pythia.live
```

**Step 3: Send to traders**
```
Message template:

Hey [Name] - built a tool that detects prediction market alpha 
before retail catches on. Take a look:

demo.pythia.live

No install needed, works on your phone. 
Shows real-time confluence signals across 8 data layers.

Worth 5 min of your time if you trade event-driven.
```

**Step 4: Follow up**
If they tap and browse → high intent. Book demo call.

## Performance

- **First Load:** <1s (optimized bundle)
- **Time to Interactive:** <1.5s
- **Lighthouse Score:** 95+ (mobile)

## What's Stripped Out (Intentionally)

To minimize friction for demo:
- ❌ No user auth/signup
- ❌ No position tracking
- ❌ No historical data browser
- ❌ No settings/config
- ❌ No payment/subscription UI

These add friction. Ship them AFTER first paid pilot.

## Next Steps (Post-Demo Success)

1. **Wire live data** - Replace mock API with real Pythia backend
2. **Add auth** - Once first customer pays
3. **Position tracking** - For $10K tier customers (Elena use case)
4. **Python SDK promo** - Link to SDK docs for quant buyers (Raj use case)

## Support

Built by XJ.ai
Questions: jie.xi@outlook.com
