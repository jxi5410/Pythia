# Pythia Demo - Deployment Guide

## ✅ Build Status

**Build completed successfully!**

Route structure:
```
○  /                    (Static - home/feed)
ƒ  /api/signals         (Dynamic API - signal list)
ƒ  /api/signals/[id]    (Dynamic API - signal detail)
ƒ  /signal/[id]         (Dynamic - signal detail page)
```

## Quick Deploy to Vercel (5 minutes)

### Option 1: Vercel CLI (Fastest)

```bash
# Install Vercel CLI
npm install -g vercel

# Login
vercel login

# Deploy (from project root)
cd /Users/xj.ai/.openclaw/workspace/projects/pythia/pythia-demo
vercel --prod

# Follow prompts:
# - Set up and deploy? Y
# - Which scope? (your account)
# - Link to existing project? N
# - Project name? pythia-demo
# - Directory? ./
# - Override settings? N

# Result: Live at pythia-demo-[hash].vercel.app in ~60 seconds
```

### Option 2: GitHub + Vercel Dashboard

```bash
# 1. Push to GitHub
cd /Users/xj.ai/.openclaw/workspace/projects/pythia/pythia-demo
git init
git add .
git commit -m "Pythia demo - zero friction mobile app"

# Create repo at github.com/new (pythia-demo)
git remote add origin https://github.com/jxi5410/pythia-demo.git
git branch -M main
git push -u origin main

# 2. Deploy via Vercel Dashboard
# - Go to https://vercel.com/new
# - Import jxi5410/pythia-demo
# - Framework: Next.js (auto-detected)
# - Click "Deploy"

# Result: Live at pythia-demo.vercel.app in ~2 minutes
```

## Custom Domain Setup

### Register Domain (if needed)

**Recommended registrar:** Cloudflare ($9.77/year for .live)

1. Go to cloudflare.com/products/registrar
2. Search: `pythia.live`
3. Register for ~$10/year

**Alternative:** Namecheap, Google Domains

### Configure DNS (Subdomain: demo.pythia.live)

**In Vercel:**
1. Open pythia-demo project
2. Settings → Domains
3. Add domain: `demo.pythia.live`
4. Copy provided DNS record:
   ```
   Type: CNAME
   Name: demo
   Value: cname.vercel-dns.com
   ```

**In your DNS provider (Cloudflare/Namecheap/etc):**
1. Go to DNS settings for pythia.live
2. Add CNAME record:
   - Name: `demo`
   - Target: `cname.vercel-dns.com`
   - TTL: Auto (or 3600)
3. Save

**Propagation:** 5-10 minutes

**Result:** `https://demo.pythia.live` → live demo

### Configure DNS (Root domain: pythia.live)

If you want `pythia.live` (not `demo.pythia.live`):

**In Vercel:**
- Add domain: `pythia.live`

**In DNS provider:**
- A record: `@` → `76.76.21.21` (Vercel IP)
- CNAME: `www` → `cname.vercel-dns.com`

## Testing the Deployment

### Mobile (iPhone)

1. Open Safari
2. Go to `https://demo.pythia.live`
3. Tap Share icon (bottom center)
4. Scroll down → "Add to Home Screen"
5. Tap "Add"
6. Launch from home screen (full-screen PWA)

### Mobile (Android)

1. Open Chrome
2. Go to `https://demo.pythia.live`
3. Tap "Install app" banner (or menu → "Install app")
4. Launch from app drawer (standalone app)

### Desktop

1. Open browser
2. Go to `https://demo.pythia.live`
3. Works as standard web app (responsive)

## Environment Variables (for Live Data)

When ready to connect to real Pythia backend:

**In Vercel Dashboard:**
1. Project Settings → Environment Variables
2. Add:
   ```
   PYTHIA_API_URL=https://pythia-backend.yourserver.com
   PYTHIA_API_KEY=your_secret_key
   ```
3. Redeploy

**In code** (`app/api/signals/route.ts`):
```typescript
const PYTHIA_API = process.env.PYTHIA_API_URL;
const API_KEY = process.env.PYTHIA_API_KEY;

export async function GET(request: Request) {
  const response = await fetch(`${PYTHIA_API}/v1/signals`, {
    headers: { 'Authorization': `Bearer ${API_KEY}` }
  });
  const data = await response.json();
  return NextResponse.json(data);
}
```

## Monitoring & Analytics

**Vercel Analytics (built-in):**
- Project Dashboard → Analytics tab
- Shows: page views, unique visitors, top pages
- Free tier: 1000 pageviews/month

**Add custom analytics:**
```bash
npm install @vercel/analytics
```

Then in `app/layout.tsx`:
```typescript
import { Analytics } from '@vercel/analytics/react';

export default function RootLayout({ children }) {
  return (
    <html>
      <body>
        {children}
        <Analytics />
      </body>
    </html>
  );
}
```

## Design Partner Outreach Message

Once deployed, send this:

```
Subject: Prediction market alpha before retail sees it

Hey [Name],

Built a tool that detects confluence signals across 8 data layers 
(Polymarket, congressional trading, Twitter velocity, etc.) before 
retail catches on.

Take a look: https://demo.pythia.live

No install needed. Works on your phone. Shows real-time signals 
with historical hit rates and edge windows.

Worth 5 min if you trade event-driven or quant strategies.

Best,
XJ
```

## Performance Metrics (Target)

- **First Load:** <1s
- **Time to Interactive:** <1.5s
- **Lighthouse Score:** 95+ (mobile)
- **Core Web Vitals:** All green

## Troubleshooting

**Build fails on Vercel:**
- Check build logs in Vercel dashboard
- Most common: TypeScript errors or missing dependencies
- Fix locally (`npm run build`), then push

**Domain not resolving:**
- Check DNS propagation: https://dnschecker.org
- Wait 10-15 minutes after adding CNAME
- Verify CNAME points to `cname.vercel-dns.com`

**App not installing on mobile:**
- Requires HTTPS (Vercel provides automatically)
- Check manifest.json is accessible: `https://demo.pythia.live/manifest.json`
- iOS: use Safari (Chrome on iOS doesn't support PWA install)

## Next Steps After First Design Partner Success

1. **Wire live data** - Connect to real Pythia backend API
2. **Add simple analytics** - Track which signals get most taps
3. **Collect feedback** - Add feedback form or Typeform link
4. **Iterate quickly** - Deploy updates take <2 minutes on Vercel

## Cost

**Free tier (sufficient for demo):**
- Vercel: 100GB bandwidth/month
- Domain: ~$10/year
- **Total: $10/year**

**Paid (if you scale):**
- Vercel Pro: $20/month (unlimited bandwidth)

---

**Built:** 24 Feb 2026  
**Status:** Production-ready  
**Next:** Deploy + send to design partners
