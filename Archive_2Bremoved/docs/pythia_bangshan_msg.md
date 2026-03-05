# Message to Bangshan — Pythia Update

---

Hey Bangshan,

Quick update — I've been building out Pythia over the past couple of days and it's now running live. Want your eyes on it as a quant.

**What it does:**
- Monitors 74 live Polymarket prediction markets in real-time (30s polling)
- Detects probability spikes, volume anomalies, momentum breakouts, and "Optimism Tax" (takers systematically overpaying for YES on longshots — based on a research paper analysing 72M trades / $18B volume)
- Every signal is enriched with: asset class mapping (rates/FX/equities/crypto), correlated markets, and news context
- Alerts formatted as trader intelligence briefings, not raw data

**The alpha thesis:**
Prediction markets are a leading sentiment indicator for macro events. When "Fed cuts March" spikes from 20% → 55%, that's aggregated informed money moving before Bloomberg catches up. Plus there's a structural maker edge: makers earn +1.12% vs takers -1.12% across all trades (documented across 72M trades on Kalshi).

**To run it yourself:**

```bash
git clone https://github.com/jxi5410/Pythia.live.git
cd Pythia.live
pip install -r requirements.txt
python run.py          # starts monitoring
# In another terminal:
streamlit run dashboard.py   # launches dashboard on localhost:8501
```

**What I want from you:**
1. Does the signal detection logic make sense from a quant perspective?
2. What signals would YOU want to see as a trader?
3. The Optimism Tax detector — is this a real exploitable edge or noise?
4. How should we think about backtesting this properly?

I've also got Jon Becker's full 36GB Polymarket/Kalshi historical dataset ready for backtesting. Repo: https://github.com/Jon-Becker/prediction-market-analysis — his research paper on prediction market microstructure is worth reading: https://jbecker.dev/research/prediction-market-microstructure

Let me know when you've had a look.
