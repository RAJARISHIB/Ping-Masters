"""Monte Carlo price simulation using Geometric Brownian Motion.

Generates stochastic price paths for stress-testing vault positions.
BNB annual volatility is typically 60-100%; default is 80%.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class SimulationConfig:
    """Parameters for the GBM price simulation."""

    n_simulations: int = 10_000
    """Number of independent Monte Carlo paths per vault."""

    horizon_hours: int = 24
    """Prediction time-window in hours."""

    dt: float = 1.0 / 24.0
    """Time-step size as a fraction of one year (1 hour ≈ 1/8760 year).
    We treat 1 day = 24 steps for intra-day resolution.
    The actual calendar duration per step is ``dt`` years."""

    base_annual_volatility: float = 0.80
    """Annualised volatility (σ).  BNB ≈ 60-100%."""

    mu: float = 0.0
    """Drift — set to 0 for risk-neutral simulation."""


def simulate_gbm_paths(
    current_price: float,
    config: SimulationConfig | None = None,
    seed: int | None = None,
) -> np.ndarray:
    """Simulate Geometric Brownian Motion price paths.

    Parameters
    ----------
    current_price:
        Starting price of the asset (human-readable, e.g. 300.0 for $300).
    config:
        Simulation hyper-parameters.  Uses defaults when *None*.
    seed:
        Optional RNG seed for reproducibility.

    Returns
    -------
    np.ndarray
        Shape ``(n_simulations, n_steps + 1)`` where column 0 is
        ``current_price`` and each subsequent column is the price at
        that time step.
    """
    if config is None:
        config = SimulationConfig()

    rng = np.random.default_rng(seed)
    n_steps = config.horizon_hours  # one step per hour

    sigma = config.base_annual_volatility
    dt = config.dt

    # Standard normal increments: (n_simulations, n_steps)
    z = rng.standard_normal((config.n_simulations, n_steps))

    # Log-return per step: (mu - σ²/2)*dt + σ*√dt * Z
    log_increments = (config.mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * z

    # Cumulative log-returns — prepend a zero column for t=0
    cumulative = np.cumsum(log_increments, axis=1)
    cumulative = np.column_stack([np.zeros(config.n_simulations), cumulative])

    return current_price * np.exp(cumulative)
