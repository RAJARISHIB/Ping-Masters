"""Forward-looking stochastic labeling — v2.0.

For each vault, simulates N GBM price paths and computes the health
factor AT EVERY TIMESTEP along each path.  A path is "liquidated" if
HF drops below 1.0 at any timestep.

    liquidation_probability = (# liquidated paths) / N
    label = 1  if  liquidation_probability > 0.5  else  0

The label is based on SIMULATED FUTURE price evolution, not on the
current health factor.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ml.config import LIQUIDATION_THRESHOLD_PERCENT
from ml.simulation.vault_generator import SyntheticVault


@dataclass
class LabelResult:
    """Labeling output for a single vault."""

    binary_label: int
    """1 = majority of Monte Carlo paths trigger liquidation, 0 = safe."""

    liquidation_probability: float
    """Fraction of simulated paths where HF dropped below 1.0 at any timestep."""


def label_vault(
    vault: SyntheticVault,
    price_paths: np.ndarray,
) -> LabelResult:
    """Label a vault via forward-looking stochastic simulation.

    Parameters
    ----------
    vault:
        The synthetic vault to evaluate.
    price_paths:
        Shape ``(n_simulations, n_steps+1)`` — one row per Monte Carlo path.

    Returns
    -------
    LabelResult
        Binary label (majority-vote at p > 0.5) and continuous probability.
    """
    if vault.debt_fiat <= 0:
        return LabelResult(binary_label=0, liquidation_probability=0.0)

    # Collateral value at every (path, timestep) point
    # shape: (n_sims, n_steps+1)
    collateral_values = vault.collateral_bnb * price_paths

    # Health factor at every (path, timestep) point
    # Canonical formula: HF = (col_val * THRESHOLD%) / (debt * 100)
    hf_all = (collateral_values * LIQUIDATION_THRESHOLD_PERCENT) / (
        vault.debt_fiat * 100
    )

    # A path is liquidated if HF < 1.0 at ANY timestep
    min_hf_per_path = hf_all.min(axis=1)  # (n_sims,)
    liquidated_mask = min_hf_per_path < 1.0

    n_liquidated = int(np.sum(liquidated_mask))
    prob = n_liquidated / len(liquidated_mask)

    # Binary label: majority-vote at p > 0.5
    return LabelResult(
        binary_label=1 if prob > 0.5 else 0,
        liquidation_probability=prob,
    )


def label_vaults_batch(
    vaults: list[SyntheticVault],
    price_paths_per_vault: list[np.ndarray],
) -> list[LabelResult]:
    """Label a batch of vaults."""
    return [
        label_vault(vault, paths)
        for vault, paths in zip(vaults, price_paths_per_vault)
    ]
