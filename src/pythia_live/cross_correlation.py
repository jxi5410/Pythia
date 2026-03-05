"""Statistical cross-market correlation engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from scipy.stats import norm, spearmanr

from .database import PythiaDB


@dataclass
class CrossCorrelationEngine:
    db: PythiaDB

    def _load_series(self, market_id: str, hours: int = 168) -> pd.Series:
        df = self.db.get_market_history(market_id, hours=hours)
        if df.empty or "timestamp" not in df or "yes_price" not in df:
            return pd.Series(dtype=float)

        ts = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
        series = pd.Series(df["yes_price"].astype(float).values, index=ts)
        series = series[~series.index.duplicated(keep="last")].sort_index()
        return series.resample("1h").last().ffill().dropna()

    def compute_correlation_matrix(self, market_ids: List[str], hours: int = 168) -> pd.DataFrame:
        data = {}
        for mid in market_ids:
            s = self._load_series(mid, hours=hours)
            if not s.empty:
                data[mid] = s

        if len(data) < 2:
            return pd.DataFrame()

        df = pd.DataFrame(data).dropna(how="all").ffill().dropna(axis=1, how="all")
        if df.shape[1] < 2:
            return pd.DataFrame()

        corr = df.corr(method="spearman")

        for i, a in enumerate(corr.columns):
            for b in corr.columns[i + 1:]:
                pair = df[[a, b]].dropna()
                if len(pair) < 20:
                    continue
                rho, pval = spearmanr(pair[a], pair[b])
                self.db.save_correlation(
                    market_id_a=a,
                    market_id_b=b,
                    spearman_rho=float(rho),
                    p_value=float(pval),
                    rolling_corr_7d=None,
                    n_observations=int(len(pair)),
                )

        return corr

    def find_statistically_correlated(
        self,
        market_id: str,
        min_correlation: float = 0.3,
        max_pvalue: float = 0.05,
    ) -> List[Dict]:
        pairs = self.db.get_correlations(market_id=market_id)
        out = []
        for row in pairs:
            if row.get("n_observations", 0) < 20:
                continue
            rho = float(row.get("spearman_rho", 0.0))
            pval = float(row.get("p_value", 1.0))
            if abs(rho) >= min_correlation and pval <= max_pvalue:
                other = row["market_id_b"] if row["market_id_a"] == market_id else row["market_id_a"]
                out.append({"market_id": other, "rho": rho, "p_value": pval, "n": row.get("n_observations", 0)})
        out.sort(key=lambda x: abs(x["rho"]), reverse=True)
        return out

    def detect_correlation_breaks(self, market_id: str, correlated_ids: List[str]) -> List[Dict]:
        breaks = []
        base = self._load_series(market_id, hours=168)
        if base.empty:
            return breaks

        for other_id in correlated_ids:
            other = self._load_series(other_id, hours=168)
            pair = pd.concat([base, other], axis=1, join="inner").dropna()
            if len(pair) < 40:
                continue

            full_rho, _ = spearmanr(pair.iloc[:, 0], pair.iloc[:, 1])
            recent = pair.iloc[-min(24 * 7, len(pair)) :]
            recent_rho, _ = spearmanr(recent.iloc[:, 0], recent.iloc[:, 1])

            if abs(full_rho) >= 0.99 or abs(recent_rho) >= 0.99:
                continue

            z_full = np.arctanh(np.clip(full_rho, -0.999, 0.999))
            z_recent = np.arctanh(np.clip(recent_rho, -0.999, 0.999))
            se = np.sqrt(1.0 / max(1, len(pair) - 3) + 1.0 / max(1, len(recent) - 3))
            z_score = abs(z_recent - z_full) / max(se, 1e-6)

            if z_score >= 2.0:
                breaks.append(
                    {
                        "market_id": market_id,
                        "other_market_id": other_id,
                        "full_corr": float(full_rho),
                        "rolling_corr_7d": float(recent_rho),
                        "z_score": float(z_score),
                        "signal_type": "CORRELATION_DEVIATION",
                    }
                )

        return breaks

    def tail_dependence_estimate(self, returns_a: List[float], returns_b: List[float], quantile: float = 0.05) -> float:
        a = np.asarray(returns_a, dtype=float)
        b = np.asarray(returns_b, dtype=float)
        n = min(len(a), len(b))
        if n < 20:
            return 0.0
        a = a[-n:]
        b = b[-n:]

        qa = np.quantile(a, quantile)
        qb = np.quantile(b, quantile)
        a_tail = a <= qa
        b_tail = b <= qb
        denom = np.sum(a_tail)
        if denom == 0:
            return 0.0
        return float(np.sum(a_tail & b_tail) / denom)

    def compute_factor_exposures(self, market_ids: List[str], hours: int = 168) -> Dict:
        data = {}
        for mid in market_ids:
            s = self._load_series(mid, hours=hours)
            if s.empty:
                continue
            rets = s.pct_change().dropna()
            if len(rets) >= 20:
                data[mid] = rets

        if len(data) < 2:
            return {"factors": [], "loadings": {}}

        mat = pd.DataFrame(data).dropna().values
        if mat.shape[0] < 10:
            return {"factors": [], "loadings": {}}

        _, singular_vals, vt = np.linalg.svd(mat, full_matrices=False)
        k = min(5, vt.shape[0])
        loadings = vt[:k, :]

        factors = []
        mids = list(data.keys())
        for i in range(k):
            idx = int(np.argmax(np.abs(loadings[i])))
            factors.append({"factor": i + 1, "label_market": mids[idx], "strength": float(singular_vals[i])})

        by_market = {mids[j]: [float(loadings[i, j]) for i in range(k)] for j in range(len(mids))}
        return {"factors": factors, "loadings": by_market}

    def get_correlation_cluster(self, market_id: str, min_abs_corr: float = 0.3) -> List[str]:
        pairs = self.db.get_correlations(market_id=market_id)
        cluster = {market_id}
        for row in pairs:
            rho = float(row.get("spearman_rho", 0.0))
            if abs(rho) < min_abs_corr:
                continue
            other = row["market_id_b"] if row["market_id_a"] == market_id else row["market_id_a"]
            cluster.add(other)
        return sorted(cluster)
