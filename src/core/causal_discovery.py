"""
Causal Discovery Engine — Directional causal relationships between markets.

Upgrades Pythia from correlation ("these move together") to causation
("this causes that, with X lag").

Methods:
  1. PCMCI (Tigramite) — constraint-based causal discovery for time series.
     Finds lagged causal links with proper conditioning.
  2. Transfer Entropy — information-theoretic measure of directional
     information flow between markets.

Both produce directed causal graphs, not symmetric correlation matrices.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Lazy imports for optional dependencies
_tigramite_available = None
_te_available = None


def _check_tigramite():
    global _tigramite_available
    if _tigramite_available is None:
        try:
            from tigramite.pcmci import PCMCI
            from tigramite.independence_tests.parcorr import ParCorr
            from tigramite import data_processing as pp
            _tigramite_available = True
        except ImportError:
            _tigramite_available = False
    return _tigramite_available


@dataclass
class CausalLink:
    """A directed causal relationship: source → target with lag."""
    source_market: str
    target_market: str
    lag_hours: int
    strength: float       # test statistic magnitude
    p_value: float
    method: str           # "pcmci" or "transfer_entropy"


@dataclass
class CausalGraph:
    """Collection of discovered causal links between markets."""
    links: List[CausalLink] = field(default_factory=list)
    market_ids: List[str] = field(default_factory=list)
    method: str = ""
    computed_at: str = ""

    def get_causes_of(self, market_id: str) -> List[CausalLink]:
        """Get all markets that causally influence this market."""
        return [l for l in self.links if l.target_market == market_id]

    def get_effects_of(self, market_id: str) -> List[CausalLink]:
        """Get all markets this market causally influences."""
        return [l for l in self.links if l.source_market == market_id]

    def get_leaders(self, top_n: int = 5) -> List[Tuple[str, int]]:
        """Markets that cause the most others (information leaders)."""
        counts = {}
        for link in self.links:
            counts[link.source_market] = counts.get(link.source_market, 0) + 1
        sorted_leaders = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        return sorted_leaders[:top_n]

    def get_followers(self, top_n: int = 5) -> List[Tuple[str, int]]:
        """Markets most caused by others (information followers)."""
        counts = {}
        for link in self.links:
            counts[link.target_market] = counts.get(link.target_market, 0) + 1
        sorted_followers = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        return sorted_followers[:top_n]

    def to_dict(self) -> Dict:
        return {
            "method": self.method,
            "n_markets": len(self.market_ids),
            "n_links": len(self.links),
            "links": [
                {
                    "source": l.source_market,
                    "target": l.target_market,
                    "lag_hours": l.lag_hours,
                    "strength": round(l.strength, 4),
                    "p_value": round(l.p_value, 4),
                }
                for l in self.links
            ],
            "leaders": self.get_leaders(),
            "followers": self.get_followers(),
        }


# ------------------------------------------------------------------ #
# Data loading helpers
# ------------------------------------------------------------------ #

def _load_aligned_returns(
    db, market_ids: List[str], hours: int = 168, resample: str = "1h"
) -> pd.DataFrame:
    """
    Load hourly returns for multiple markets, aligned to a common time index.
    Returns DataFrame where columns are market_ids and values are price changes.
    """
    series_dict = {}
    for mid in market_ids:
        df = db.get_market_history(mid, hours=hours)
        if df.empty or "timestamp" not in df or "yes_price" not in df:
            continue

        ts = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
        s = pd.Series(df["yes_price"].astype(float).values, index=ts)
        s = s[~s.index.duplicated(keep="last")].sort_index()
        s = s.resample(resample).last().ffill().dropna()

        if len(s) >= 20:
            series_dict[mid] = s

    if len(series_dict) < 2:
        return pd.DataFrame()

    panel = pd.DataFrame(series_dict).dropna()
    # Convert to returns for stationarity
    returns = panel.diff().iloc[1:]
    return returns.dropna(axis=1, how="all").dropna()


# ------------------------------------------------------------------ #
# Method 1: PCMCI — Constraint-based causal discovery
# ------------------------------------------------------------------ #

def discover_causal_graph_pcmci(
    db,
    market_ids: List[str],
    hours: int = 168,
    max_lag: int = 6,
    alpha_level: float = 0.05,
) -> CausalGraph:
    """
    Discover lagged causal relationships between markets using PCMCI.

    PCMCI (Peter-Clark Momentary Conditional Independence) properly conditions
    on other variables and lags, avoiding the spurious correlations that
    plague simple Granger causality.

    Args:
        db: PythiaDB instance
        market_ids: Markets to include in the causal graph
        hours: Lookback window for data (default 7 days)
        max_lag: Maximum lag in hours to test (default 6h)
        alpha_level: Significance threshold (default 0.05)

    Returns:
        CausalGraph with directed links and lag structure
    """
    if not _check_tigramite():
        logger.warning("tigramite not installed — skipping PCMCI")
        return CausalGraph(method="pcmci_unavailable")

    from tigramite.pcmci import PCMCI
    from tigramite.independence_tests.parcorr import ParCorr
    from tigramite import data_processing as pp

    returns = _load_aligned_returns(db, market_ids, hours=hours)
    if returns.empty or returns.shape[1] < 2:
        logger.warning("Insufficient data for PCMCI (%s)", returns.shape)
        return CausalGraph(method="pcmci_insufficient_data")

    # Cap at 15 markets to keep computation tractable
    if returns.shape[1] > 15:
        # Keep the 15 with highest variance (most active)
        variances = returns.var().sort_values(ascending=False)
        keep = variances.index[:15].tolist()
        returns = returns[keep]

    active_ids = returns.columns.tolist()
    data_array = returns.values
    n_vars = data_array.shape[1]

    logger.info(
        "Running PCMCI: %d markets, %d observations, max_lag=%d",
        n_vars, data_array.shape[0], max_lag,
    )

    # Build tigramite dataframe
    dataframe = pp.DataFrame(
        data=data_array,
        var_names=active_ids,
    )

    # Run PCMCI with ParCorr (linear, fast, works well with <200 data points)
    pcmci = PCMCI(dataframe=dataframe, cond_ind_test=ParCorr())

    try:
        results = pcmci.run_pcmci(tau_max=max_lag, pc_alpha=alpha_level)
    except Exception as e:
        logger.error("PCMCI failed: %s", e)
        return CausalGraph(method="pcmci_error")

    # Extract significant links
    p_matrix = results["p_matrix"]
    val_matrix = results["val_matrix"]

    links = []
    for target_idx in range(n_vars):
        for source_idx in range(n_vars):
            if source_idx == target_idx:
                continue
            for lag in range(1, max_lag + 1):
                p_val = float(p_matrix[source_idx, target_idx, lag])
                strength = float(abs(val_matrix[source_idx, target_idx, lag]))

                if p_val <= alpha_level and strength > 0.05:
                    links.append(CausalLink(
                        source_market=active_ids[source_idx],
                        target_market=active_ids[target_idx],
                        lag_hours=lag,
                        strength=strength,
                        p_value=p_val,
                        method="pcmci",
                    ))

    # Sort by strength
    links.sort(key=lambda l: l.strength, reverse=True)

    graph = CausalGraph(
        links=links,
        market_ids=active_ids,
        method="pcmci",
        computed_at=pd.Timestamp.utcnow().isoformat(),
    )

    logger.info(
        "PCMCI complete: %d significant causal links found among %d markets",
        len(links), n_vars,
    )

    return graph


# ------------------------------------------------------------------ #
# Method 2: Transfer Entropy — Information flow detection
# ------------------------------------------------------------------ #

def _discretize_series(series: np.ndarray, n_bins: int = 5) -> np.ndarray:
    """Discretize continuous values into bins for transfer entropy."""
    if len(series) < n_bins:
        return np.zeros(len(series), dtype=int)
    percentiles = np.linspace(0, 100, n_bins + 1)
    edges = np.percentile(series, percentiles)
    # Ensure unique edges
    edges = np.unique(edges)
    if len(edges) < 2:
        return np.zeros(len(series), dtype=int)
    return np.clip(np.digitize(series, edges[1:-1]), 0, len(edges) - 2)


def _compute_transfer_entropy(
    source: np.ndarray, target: np.ndarray, lag: int = 1, n_bins: int = 5
) -> float:
    """
    Compute transfer entropy from source to target: TE(source → target).

    Transfer entropy measures the reduction in uncertainty of target's future
    when we know source's past, beyond what target's own past tells us.

    TE(X→Y) = H(Y_future | Y_past) - H(Y_future | Y_past, X_past)

    Implementation uses discrete binning for robustness with limited data.
    """
    if len(source) < lag + 10 or len(target) < lag + 10:
        return 0.0

    # Discretize
    src_d = _discretize_series(source, n_bins)
    tgt_d = _discretize_series(target, n_bins)

    n = len(tgt_d) - lag
    if n < 10:
        return 0.0

    # Build joint distributions
    # Y_future, Y_past, X_past
    y_future = tgt_d[lag:][:n]
    y_past = tgt_d[:-lag][:n] if lag > 0 else tgt_d[:n]
    x_past = src_d[:-lag][:n] if lag > 0 else src_d[:n]

    # TE = H(Y_f | Y_p) - H(Y_f | Y_p, X_p)
    # Using conditional entropy formulas

    def _joint_entropy(*arrays):
        """Compute joint entropy of discrete arrays."""
        combined = np.column_stack(arrays)
        _, counts = np.unique(combined, axis=0, return_counts=True)
        probs = counts / counts.sum()
        return -np.sum(probs * np.log2(probs + 1e-12))

    # H(Y_f, Y_p) - H(Y_p) = H(Y_f | Y_p)
    h_yf_yp = _joint_entropy(y_future, y_past)
    h_yp = _joint_entropy(y_past)
    h_cond_yp = h_yf_yp - h_yp

    # H(Y_f, Y_p, X_p) - H(Y_p, X_p) = H(Y_f | Y_p, X_p)
    h_yf_yp_xp = _joint_entropy(y_future, y_past, x_past)
    h_yp_xp = _joint_entropy(y_past, x_past)
    h_cond_yp_xp = h_yf_yp_xp - h_yp_xp

    te = h_cond_yp - h_cond_yp_xp
    return max(0.0, te)  # TE is non-negative in theory


def _te_significance(
    source: np.ndarray,
    target: np.ndarray,
    observed_te: float,
    lag: int = 1,
    n_shuffles: int = 100,
    n_bins: int = 5,
) -> float:
    """
    Compute p-value for transfer entropy using permutation test.
    Shuffles source series to destroy temporal structure and computes null TE.
    """
    if observed_te <= 0:
        return 1.0

    null_tes = []
    rng = np.random.default_rng(42)
    for _ in range(n_shuffles):
        shuffled_source = rng.permutation(source)
        null_te = _compute_transfer_entropy(shuffled_source, target, lag, n_bins)
        null_tes.append(null_te)

    null_tes = np.array(null_tes)
    p_value = float(np.mean(null_tes >= observed_te))
    return p_value


def compute_transfer_entropy_matrix(
    db,
    market_ids: List[str],
    hours: int = 168,
    lag: int = 1,
    n_bins: int = 5,
    alpha_level: float = 0.05,
) -> CausalGraph:
    """
    Compute pairwise transfer entropy between all markets.

    For each pair (A, B), computes both TE(A→B) and TE(B→A).
    The asymmetry reveals directional information flow.

    Args:
        db: PythiaDB instance
        market_ids: Markets to analyze
        hours: Lookback window
        lag: Lag in hours for TE computation
        n_bins: Discretization bins
        alpha_level: Significance threshold for permutation test

    Returns:
        CausalGraph with directed information flow links
    """
    returns = _load_aligned_returns(db, market_ids, hours=hours)
    if returns.empty or returns.shape[1] < 2:
        return CausalGraph(method="transfer_entropy_insufficient_data")

    # Cap at 10 markets (TE is O(n^2) with permutation tests)
    if returns.shape[1] > 10:
        variances = returns.var().sort_values(ascending=False)
        keep = variances.index[:10].tolist()
        returns = returns[keep]

    active_ids = returns.columns.tolist()
    n_vars = len(active_ids)

    logger.info(
        "Computing transfer entropy: %d markets, %d observations, lag=%d",
        n_vars, len(returns), lag,
    )

    links = []

    for i in range(n_vars):
        for j in range(n_vars):
            if i == j:
                continue

            source = returns.iloc[:, i].values
            target = returns.iloc[:, j].values

            te = _compute_transfer_entropy(source, target, lag=lag, n_bins=n_bins)

            if te > 0.01:  # Only test significance if TE is non-trivial
                p_val = _te_significance(source, target, te, lag=lag, n_bins=n_bins)

                if p_val <= alpha_level:
                    links.append(CausalLink(
                        source_market=active_ids[i],
                        target_market=active_ids[j],
                        lag_hours=lag,
                        strength=float(te),
                        p_value=float(p_val),
                        method="transfer_entropy",
                    ))

    links.sort(key=lambda l: l.strength, reverse=True)

    graph = CausalGraph(
        links=links,
        market_ids=active_ids,
        method="transfer_entropy",
        computed_at=pd.Timestamp.utcnow().isoformat(),
    )

    logger.info(
        "Transfer entropy complete: %d significant links among %d markets",
        len(links), n_vars,
    )

    return graph


def detect_information_flow(
    db,
    market_a_id: str,
    market_b_id: str,
    hours: int = 168,
    max_lag: int = 6,
) -> Dict:
    """
    Measure directional information flow between two specific markets.

    Returns which market leads and by how many hours.
    """
    returns = _load_aligned_returns(db, [market_a_id, market_b_id], hours=hours)
    if returns.empty or returns.shape[1] < 2:
        return {"error": "insufficient_data"}

    a_vals = returns.iloc[:, 0].values
    b_vals = returns.iloc[:, 1].values
    a_id = returns.columns[0]
    b_id = returns.columns[1]

    best_lag_a_to_b = {"te": 0, "lag": 0, "p_value": 1.0}
    best_lag_b_to_a = {"te": 0, "lag": 0, "p_value": 1.0}

    for lag in range(1, max_lag + 1):
        te_ab = _compute_transfer_entropy(a_vals, b_vals, lag=lag)
        te_ba = _compute_transfer_entropy(b_vals, a_vals, lag=lag)

        if te_ab > best_lag_a_to_b["te"]:
            p_ab = _te_significance(a_vals, b_vals, te_ab, lag=lag, n_shuffles=50)
            best_lag_a_to_b = {"te": te_ab, "lag": lag, "p_value": p_ab}

        if te_ba > best_lag_b_to_a["te"]:
            p_ba = _te_significance(b_vals, a_vals, te_ba, lag=lag, n_shuffles=50)
            best_lag_b_to_a = {"te": te_ba, "lag": lag, "p_value": p_ba}

    # Determine net direction
    net_te = best_lag_a_to_b["te"] - best_lag_b_to_a["te"]

    if abs(net_te) < 0.01:
        direction = "bidirectional"
    elif net_te > 0:
        direction = f"{a_id} → {b_id}"
    else:
        direction = f"{b_id} → {a_id}"

    return {
        "market_a": a_id,
        "market_b": b_id,
        "te_a_to_b": round(best_lag_a_to_b["te"], 4),
        "te_b_to_a": round(best_lag_b_to_a["te"], 4),
        "best_lag_a_to_b": best_lag_a_to_b["lag"],
        "best_lag_b_to_a": best_lag_b_to_a["lag"],
        "p_value_a_to_b": round(best_lag_a_to_b["p_value"], 4),
        "p_value_b_to_a": round(best_lag_b_to_a["p_value"], 4),
        "net_direction": direction,
        "asymmetry": round(abs(net_te), 4),
    }


# ------------------------------------------------------------------ #
# Combined: Run both methods and merge
# ------------------------------------------------------------------ #

def discover_full_causal_graph(
    db,
    market_ids: List[str],
    hours: int = 168,
    max_lag: int = 6,
    alpha_level: float = 0.05,
) -> Dict:
    """
    Run both PCMCI and Transfer Entropy, merge results.

    Links found by both methods are marked as high-confidence.
    """
    pcmci_graph = discover_causal_graph_pcmci(
        db, market_ids, hours=hours, max_lag=max_lag, alpha_level=alpha_level,
    )

    te_graph = compute_transfer_entropy_matrix(
        db, market_ids, hours=hours, lag=1, alpha_level=alpha_level,
    )

    # Find links confirmed by both methods
    pcmci_pairs = {
        (l.source_market, l.target_market) for l in pcmci_graph.links
    }
    te_pairs = {
        (l.source_market, l.target_market) for l in te_graph.links
    }
    confirmed = pcmci_pairs & te_pairs

    return {
        "pcmci": pcmci_graph.to_dict(),
        "transfer_entropy": te_graph.to_dict(),
        "confirmed_by_both": [
            {"source": s, "target": t} for s, t in confirmed
        ],
        "n_confirmed": len(confirmed),
        "summary": {
            "pcmci_links": len(pcmci_graph.links),
            "te_links": len(te_graph.links),
            "confirmed_links": len(confirmed),
            "markets_analyzed": len(market_ids),
        },
    }
