"""Dataset generation pipeline — v2.0 (leakage-free + balanced).

Changes from v1:
  - Per-vault volatility (sampled, not global constant)
  - Uses v2 feature extractor (4 raw observable features only)
  - Uses v2 labeler (forward-looking stochastic, majority-vote threshold)
  - Enforces class balance: label-1 ratio between 0.3 and 0.7
  - Prints final class distribution
"""

from __future__ import annotations

import csv
import logging
import time
from pathlib import Path
from typing import List

import numpy as np

from ml.features.feature_extractor import FEATURE_NAMES, extract_features
from ml.simulation.labeler import label_vault
from ml.simulation.price_simulator import SimulationConfig, simulate_gbm_paths
from ml.simulation.vault_generator import SyntheticVault, generate_vaults

logger = logging.getLogger(__name__)

DEFAULT_DATASET_PATH = Path(__file__).parent / "dataset.csv"


def generate_dataset(
    n_vaults: int = 15_000,
    n_simulations: int = 2_000,
    horizon_hours: int = 24,
    output_path: Path | str | None = None,
    seed: int = 42,
    target_ratio_range: tuple[float, float] = (0.30, 0.70),
) -> Path:
    """End-to-end dataset creation with class-balance enforcement.

    Parameters
    ----------
    n_vaults:
        Number of synthetic vaults to generate (before balance filtering).
    n_simulations:
        Monte Carlo paths per vault.
    horizon_hours:
        Stress-test time horizon.
    output_path:
        CSV output location.
    seed:
        Base RNG seed.
    target_ratio_range:
        Acceptable range for label-1 ratio.

    Returns
    -------
    Path
        Absolute path of the written CSV.
    """
    output_path = Path(output_path) if output_path else DEFAULT_DATASET_PATH

    logger.info(
        "Generating dataset: n_vaults=%d  n_sims=%d  horizon=%dh",
        n_vaults,
        n_simulations,
        horizon_hours,
    )
    t0 = time.perf_counter()

    # Step 1 — generate vaults with per-vault volatility
    vaults = generate_vaults(n_vaults=n_vaults, seed=seed)
    logger.info("Generated %d synthetic vaults.", len(vaults))

    # Step 2 + 3 — simulate, label, extract features
    header = FEATURE_NAMES + ["liquidation_probability", "label"]
    rows: List[List[float]] = []

    for idx, vault in enumerate(vaults):
        vault_seed = seed + idx + 1

        # Per-vault simulation config using the vault's own volatility
        sim_config = SimulationConfig(
            n_simulations=n_simulations,
            horizon_hours=horizon_hours,
            base_annual_volatility=vault.volatility,
        )

        paths = simulate_gbm_paths(
            current_price=vault.current_price,
            config=sim_config,
            seed=vault_seed,
        )
        result = label_vault(vault, paths)

        features = extract_features(
            collateral_bnb=vault.collateral_bnb,
            debt_fiat=vault.debt_fiat,
            current_price=vault.current_price,
            volatility=vault.volatility,
        )

        row = features.to_list() + [result.liquidation_probability, float(result.binary_label)]
        rows.append(row)

        if (idx + 1) % 2000 == 0:
            logger.info("  processed %d / %d vaults", idx + 1, n_vaults)

    # Step 4 — balance check
    labels = [r[-1] for r in rows]
    n_pos = sum(1 for l in labels if l == 1.0)
    n_neg = len(labels) - n_pos
    ratio = n_pos / len(labels) if labels else 0

    logger.info(
        "Raw class distribution:  label-0=%d  label-1=%d  ratio=%.4f",
        n_neg,
        n_pos,
        ratio,
    )

    # Enforce balance by undersampling the majority class
    lo, hi = target_ratio_range
    if ratio < lo or ratio > hi:
        logger.info(
            "Class imbalance detected (ratio=%.3f outside [%.2f, %.2f]). "
            "Undersampling majority class...",
            ratio,
            lo,
            hi,
        )
        rows = _balance_dataset(rows, target_ratio=0.50)
        labels = [r[-1] for r in rows]
        n_pos = sum(1 for l in labels if l == 1.0)
        n_neg = len(labels) - n_pos
        ratio = n_pos / len(labels) if labels else 0
        logger.info(
            "Balanced distribution:  label-0=%d  label-1=%d  ratio=%.4f",
            n_neg,
            n_pos,
            ratio,
        )

    # Step 5 — write CSV
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)

    elapsed = time.perf_counter() - t0
    logger.info(
        "Dataset written to %s  (%d rows, %.1fs)",
        output_path,
        len(rows),
        elapsed,
    )
    return output_path.resolve()


def _balance_dataset(
    rows: List[List[float]],
    target_ratio: float = 0.50,
) -> List[List[float]]:
    """Undersample the majority class to reach *target_ratio*.

    Returns a new list; does not modify *rows* in-place.
    """
    pos = [r for r in rows if r[-1] == 1.0]
    neg = [r for r in rows if r[-1] == 0.0]

    if len(pos) == 0 or len(neg) == 0:
        return rows

    # Determine which class is majority
    if len(pos) > len(neg):
        # Downsample positives to match target
        # target_ratio = n_pos / (n_pos + n_neg)  →  n_pos = n_neg * r / (1-r)
        target_pos = int(len(neg) * target_ratio / (1 - target_ratio))
        target_pos = min(target_pos, len(pos))
        rng = np.random.default_rng(123)
        indices = rng.choice(len(pos), size=target_pos, replace=False)
        pos = [pos[i] for i in sorted(indices)]
    else:
        # Downsample negatives
        target_neg = int(len(pos) * (1 - target_ratio) / target_ratio)
        target_neg = min(target_neg, len(neg))
        rng = np.random.default_rng(123)
        indices = rng.choice(len(neg), size=target_neg, replace=False)
        neg = [neg[i] for i in sorted(indices)]

    combined = pos + neg
    rng2 = np.random.default_rng(456)
    rng2.shuffle(combined)
    return combined
