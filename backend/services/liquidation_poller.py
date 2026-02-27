"""Background liquidation poller service for Web3-enabled recovery automation.

FIX APPLIED: Health factor from the contract is scaled by 1e18
(i.e. ``1.0`` on-chain = ``1_000_000_000_000_000_000``).  The
previous code compared the raw integer against ``float(1.0)`` which
meant liquidation would **never** trigger.

The fix divides the raw value by ``PRECISION`` (1e18) before comparing
against the threshold.
"""

import asyncio
import json
import logging
from typing import Any, Optional

from web3 import Web3

from common.protocol_constants import PRECISION, raw_to_human_hf
from core.config import AppSettings


logger = logging.getLogger(__name__)


class LiquidationPoller:
    """Continuously poll borrower health and execute liquidation when required."""

    def __init__(self, settings: AppSettings) -> None:
        """Create a poller with environment-driven configuration."""
        self._settings = settings
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._w3: Optional[Web3] = None
        self._contract: Any = None

    def _is_enabled(self) -> bool:
        """Return whether poller feature is enabled."""
        return self._settings.liquidator_enabled

    def _is_config_complete(self) -> bool:
        """Validate required runtime configuration values."""
        return all(
            [
                self._settings.liquidator_rpc_url,
                self._settings.liquidator_contract_address,
                self._settings.liquidator_contract_abi_json,
                self._settings.liquidator_private_key,
                self._settings.liquidator_address,
            ]
        )

    def _initialize_web3(self) -> None:
        """Initialize Web3 client and contract handle."""
        try:
            abi = json.loads(self._settings.liquidator_contract_abi_json or "[]")
            self._w3 = Web3(Web3.HTTPProvider(self._settings.liquidator_rpc_url))
            contract_address = Web3.to_checksum_address(self._settings.liquidator_contract_address or "")
            self._contract = self._w3.eth.contract(address=contract_address, abi=abi)
            logger.info("Liquidation poller initialized with contract=%s", contract_address)
        except Exception:
            logger.exception("Failed to initialize liquidation poller Web3 dependencies.")
            raise

    async def start(self) -> None:
        """Start polling loop in background task if enabled and configured."""
        if not self._is_enabled():
            logger.info("Liquidation poller disabled by LIQUIDATOR_ENABLED=false")
            return
        if not self._is_config_complete():
            logger.warning("Liquidation poller enabled but configuration is incomplete.")
            return
        if self._task and not self._task.done():
            logger.info("Liquidation poller already running.")
            return

        try:
            self._initialize_web3()
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run_loop(), name="liquidation-poller")
            logger.info("Liquidation poller started.")
        except Exception:
            logger.exception("Failed to start liquidation poller.")

    async def stop(self) -> None:
        """Gracefully stop background polling task."""
        if not self._task:
            return
        self._stop_event.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            logger.info("Liquidation poller task cancelled.")
        except Exception:
            logger.exception("Unexpected error while stopping liquidation poller.")
        finally:
            self._task = None

    async def _run_loop(self) -> None:
        """Main polling loop for liquidation checks."""
        logger.info("Liquidation poller loop running.")
        while not self._stop_event.is_set():
            try:
                await self._poll_once()
            except Exception:
                logger.exception("Unhandled error during liquidation poll cycle.")

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=float(self._settings.liquidator_poll_interval_sec),
                )
            except asyncio.TimeoutError:
                continue

    async def _poll_once(self) -> None:
        """Execute one liquidation-check cycle across configured borrowers."""
        if self._w3 is None or self._contract is None:
            logger.warning("Liquidation poller dependencies not initialized.")
            return

        borrowers = self._settings.liquidator_borrowers
        if not borrowers:
            logger.debug("No borrowers configured for liquidation polling.")
            return

        bnb_price = self._read_optional_price()
        logger.info("Liquidation cycle started borrowers=%d price=%s", len(borrowers), bnb_price)

        for borrower in borrowers:
            await self._evaluate_borrower(borrower)

    def _read_optional_price(self) -> Any:
        """Read and return optional price function if available."""
        if self._contract is None:
            return None
        try:
            function = getattr(self._contract.functions, self._settings.liquidator_price_function)
            return function().call()
        except Exception:
            logger.debug(
                "Price function unavailable or failed function=%s",
                self._settings.liquidator_price_function,
            )
            return None

    async def _evaluate_borrower(self, borrower_address: str) -> None:
        """Check borrower health factor and trigger liquidation if required.

        **FIX**: The contract returns health factor as a uint256 scaled
        by 1e18 (``PRECISION``).  We convert to a human-readable float
        before comparing against the threshold (default 1.0).
        """
        if self._contract is None:
            return

        try:
            function = getattr(self._contract.functions, self._settings.liquidator_health_function)
            raw_health_factor = function(borrower_address).call()

            # ───────────────────────────────────────────────────────
            # FIX: Convert 1e18-scaled integer to human-readable float
            # Before: float(raw_health_factor) < threshold   — ALWAYS FALSE
            # After:  raw_health_factor / 1e18 < threshold   — CORRECT
            # ───────────────────────────────────────────────────────
            human_hf = raw_to_human_hf(int(raw_health_factor))
            threshold = self._settings.liquidator_health_threshold

            logger.info(
                "Borrower health checked borrower=%s raw_hf=%s human_hf=%.6f threshold=%s",
                borrower_address,
                raw_health_factor,
                human_hf,
                threshold,
            )

            if human_hf < threshold:
                logger.warning(
                    "Borrower below threshold. Triggering liquidation borrower=%s human_hf=%.6f",
                    borrower_address,
                    human_hf,
                )
                self._execute_liquidation(borrower_address)
        except Exception:
            logger.exception("Failed borrower evaluation borrower=%s", borrower_address)

    def _execute_liquidation(self, borrower_address: str) -> None:
        """Build, sign, and submit liquidation transaction."""
        if self._w3 is None or self._contract is None:
            logger.warning("Cannot execute liquidation. Web3 contract not initialized.")
            return

        try:
            liquidator_address = self._settings.liquidator_address or ""
            private_key = self._settings.liquidator_private_key or ""
            nonce = self._w3.eth.get_transaction_count(liquidator_address)
            function = getattr(self._contract.functions, self._settings.liquidator_execute_function)
            tx = function(borrower_address).build_transaction(
                {
                    "chainId": self._settings.liquidator_chain_id,
                    "gas": self._settings.liquidator_gas_limit,
                    "gasPrice": self._w3.to_wei(self._settings.liquidator_gas_price_gwei, "gwei"),
                    "nonce": nonce,
                }
            )
            signed_tx = self._w3.eth.account.sign_transaction(tx, private_key)
            raw_tx = getattr(signed_tx, "rawTransaction", None)
            if raw_tx is None:
                raw_tx = getattr(signed_tx, "raw_transaction")
            tx_hash = self._w3.eth.send_raw_transaction(raw_tx)
            logger.info("Liquidation transaction sent borrower=%s tx_hash=%s", borrower_address, tx_hash.hex())
        except Exception:
            logger.exception("Liquidation transaction failed borrower=%s", borrower_address)
