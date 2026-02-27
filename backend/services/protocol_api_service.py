"""Protocol API simulation service aligned with API documentation endpoints."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import threading
from typing import Dict, List, Optional
from uuid import uuid4


logger = logging.getLogger(__name__)

USD = "USD"
INR = "INR"
ALLOWED_CURRENCIES = {USD, INR}


def _now_epoch() -> int:
    """Return current UTC epoch seconds."""
    return int(datetime.now(timezone.utc).timestamp())


def _safe_float(value: str) -> float:
    """Parse numeric string into float."""
    return float(value)


@dataclass
class Position:
    """In-memory account position."""

    wallet: str
    collateral_bnb: float = 0.0
    debt: float = 0.0
    currency: Optional[str] = None
    currency_set: bool = False

    def health_factor(self, bnb_price_fiat: float) -> float:
        """Calculate health factor using max LTV 75%."""
        if self.debt <= 0:
            return 999999.0
        collateral_fiat = self.collateral_bnb * bnb_price_fiat
        max_debt = collateral_fiat * 0.75
        if max_debt <= 0:
            return 0.0
        return max_debt / self.debt


@dataclass
class LiquidationRecord:
    """In-memory liquidation archive record."""

    id: int
    borrower: str
    liquidator: str
    debt_repaid: float
    collateral_seized_bnb: float
    bonus_bnb: float
    currency: str
    bsc_block: int
    bsc_tx_hash: str
    opbnb_timestamp: int


@dataclass
class ProtocolState:
    """Holds mutable protocol state."""

    usd_price: int = 0
    inr_price: int = 0
    usd_last_updated: int = 0
    inr_last_updated: int = 0
    positions: Dict[str, Position] = field(default_factory=dict)
    archive: List[LiquidationRecord] = field(default_factory=list)


class ProtocolApiService:
    """Implements protocol endpoints for hackathon backend API layer."""

    def __init__(self) -> None:
        self._state = ProtocolState()
        self._lock = threading.RLock()

    def update_prices(self, usd_price: int, inr_price: int) -> dict:
        """Update oracle prices."""
        if usd_price <= 0 or inr_price <= 0:
            raise ValueError("Price must be > 0")
        with self._lock:
            now = _now_epoch()
            self._state.usd_price = usd_price
            self._state.inr_price = inr_price
            self._state.usd_last_updated = now
            self._state.inr_last_updated = now
            return {
                "tx_hash": "0x{0}".format(uuid4().hex),
                "usd_price": usd_price,
                "inr_price": inr_price,
                "updated_at": now,
            }

    def get_prices(self) -> dict:
        """Get current prices."""
        with self._lock:
            return {
                "usd_price": self._state.usd_price,
                "inr_price": self._state.inr_price,
                "usd_last_updated": self._state.usd_last_updated,
                "inr_last_updated": self._state.inr_last_updated,
            }

    def set_currency(self, wallet: str, currency: str) -> dict:
        """Set user currency preference if no outstanding debt."""
        normalized = currency.upper()
        if normalized not in ALLOWED_CURRENCIES:
            raise ValueError("currency must be USD or INR")
        with self._lock:
            position = self._state.positions.setdefault(wallet, Position(wallet=wallet))
            if position.debt > 0 and position.currency and position.currency != normalized:
                raise RuntimeError("Cannot change currency while account has outstanding debt")
            position.currency = normalized
            position.currency_set = True
            return {
                "wallet": wallet,
                "currency": normalized,
                "tx_hash": "0x{0}".format(uuid4().hex),
            }

    def deposit_collateral(self, wallet: str, amount_bnb: str) -> dict:
        """Deposit collateral."""
        amount = _safe_float(amount_bnb)
        if amount <= 0:
            raise ValueError("amount_bnb must be > 0")
        with self._lock:
            position = self._state.positions.setdefault(wallet, Position(wallet=wallet))
            position.collateral_bnb += amount
            return {
                "wallet": wallet,
                "deposited_bnb": str(amount),
                "total_collateral_bnb": str(position.collateral_bnb),
                "tx_hash": "0x{0}".format(uuid4().hex),
            }

    def withdraw_collateral(self, wallet: str, amount_bnb: str) -> dict:
        """Withdraw collateral if health remains safe."""
        amount = _safe_float(amount_bnb)
        if amount <= 0:
            raise ValueError("amount_bnb must be > 0")
        with self._lock:
            position = self._state.positions.setdefault(wallet, Position(wallet=wallet))
            if amount > position.collateral_bnb:
                raise ValueError("Withdrawal amount exceeds collateral")
            price = self._price_for_position(position)
            remaining = position.collateral_bnb - amount
            simulated = Position(
                wallet=wallet,
                collateral_bnb=remaining,
                debt=position.debt,
                currency=position.currency,
                currency_set=position.currency_set,
            )
            if position.debt > 0 and simulated.health_factor(price) < 1.0:
                raise ValueError("Withdrawal would breach collateral threshold")
            position.collateral_bnb = remaining
            return {
                "wallet": wallet,
                "withdrawn_bnb": str(amount),
                "remaining_collateral_bnb": str(position.collateral_bnb),
                "tx_hash": "0x{0}".format(uuid4().hex),
            }

    def borrow(self, wallet: str, amount: str, currency: Optional[str]) -> dict:
        """Borrow fiat debt tokens."""
        amount_float = _safe_float(amount)
        if amount_float <= 0:
            raise ValueError("amount must be > 0")
        with self._lock:
            position = self._state.positions.setdefault(wallet, Position(wallet=wallet))
            if currency:
                currency_norm = currency.upper()
                if currency_norm not in ALLOWED_CURRENCIES:
                    raise ValueError("currency must be USD or INR")
                if position.debt > 0 and position.currency and position.currency != currency_norm:
                    raise RuntimeError("Cannot change currency while account has outstanding debt")
                position.currency = currency_norm
                position.currency_set = True
            if not position.currency:
                raise ValueError("currency is required for first borrow")

            bnb_price = self._price_for_position(position)
            collateral_fiat = position.collateral_bnb * bnb_price
            max_debt = collateral_fiat * 0.75
            if (position.debt + amount_float) > max_debt:
                raise ValueError("Borrow limit exceeded - max LTV is 75%")

            position.debt += amount_float
            health = position.health_factor(bnb_price)
            return {
                "wallet": wallet,
                "borrowed": str(amount_float),
                "currency": position.currency,
                "token": "pm{0}".format(position.currency),
                "health_factor": str(round(health, 4)),
                "tx_hash": "0x{0}".format(uuid4().hex),
            }

    def repay(self, wallet: str, amount: str) -> dict:
        """Repay existing debt."""
        amount_float = _safe_float(amount)
        if amount_float <= 0:
            raise ValueError("amount must be > 0")
        with self._lock:
            position = self._state.positions.get(wallet)
            if position is None:
                raise KeyError("Wallet not found")
            if position.debt <= 0:
                raise ValueError("No outstanding debt")
            repaid = min(amount_float, position.debt)
            position.debt -= repaid
            health = position.health_factor(self._price_for_position(position))
            return {
                "wallet": wallet,
                "repaid": str(repaid),
                "currency": position.currency,
                "remaining_debt": str(position.debt),
                "health_factor": str(round(health, 4)),
                "tx_hash": "0x{0}".format(uuid4().hex),
            }

    def account(self, wallet: str) -> dict:
        """Fetch account status."""
        with self._lock:
            position = self._state.positions.get(wallet)
            if position is None:
                raise KeyError("Wallet not found")
            return self._position_to_payload(position)

    def all_positions(self, liquidatable_only: bool = False) -> dict:
        """List all positions."""
        with self._lock:
            records = []
            for position in self._state.positions.values():
                payload = self._position_to_payload(position)
                if liquidatable_only and not payload["is_liquidatable"]:
                    continue
                records.append(payload)
            return {"total": len(records), "positions": records}

    def liquidate(self, wallet: str, liquidator: str = "0xBotAddress") -> dict:
        """Liquidate an unhealthy position and archive the event."""
        with self._lock:
            position = self._state.positions.get(wallet)
            if position is None:
                raise KeyError("Wallet not found")
            payload = self._position_to_payload(position)
            if not payload["is_liquidatable"]:
                raise ValueError("Position is healthy - cannot liquidate")

            debt = position.debt
            bnb_price = self._price_for_position(position)
            collateral_seized = min(position.collateral_bnb, (debt / bnb_price) * 1.05 if bnb_price > 0 else 0.0)
            bonus = collateral_seized * 0.05

            position.debt = 0.0
            position.collateral_bnb = max(0.0, position.collateral_bnb - collateral_seized)

            record = LiquidationRecord(
                id=len(self._state.archive),
                borrower=wallet,
                liquidator=liquidator,
                debt_repaid=debt,
                collateral_seized_bnb=collateral_seized,
                bonus_bnb=bonus,
                currency=position.currency or USD,
                bsc_block=10000000 + len(self._state.archive),
                bsc_tx_hash="0x{0}".format(uuid4().hex),
                opbnb_timestamp=_now_epoch(),
            )
            self._state.archive.append(record)

            return {
                "borrower": wallet,
                "liquidator": liquidator,
                "debt_repaid": str(round(debt, 6)),
                "collateral_seized_bnb": str(round(collateral_seized, 6)),
                "bonus_bnb": str(round(bonus, 6)),
                "currency": record.currency,
                "bsc_tx_hash": record.bsc_tx_hash,
                "opbnb_tx_hash": "0x{0}".format(uuid4().hex),
                "archive_record_id": record.id,
            }

    def archive_liquidations(self, page: int, page_size: int, currency: Optional[str]) -> dict:
        """Return paginated liquidation archive."""
        with self._lock:
            records = self._state.archive
            if currency:
                currency_norm = currency.upper()
                records = [item for item in records if item.currency == currency_norm]
            total = len(records)
            start = page * page_size
            end = start + page_size
            paged = records[start:end]
            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "records": [
                    {
                        "id": item.id,
                        "borrower": item.borrower,
                        "liquidator": item.liquidator,
                        "debt_repaid": str(round(item.debt_repaid, 6)),
                        "collateral_seized_bnb": str(round(item.collateral_seized_bnb, 6)),
                        "bonus_bnb": str(round(item.bonus_bnb, 6)),
                        "currency": item.currency,
                        "bsc_block": item.bsc_block,
                        "bsc_tx_hash": item.bsc_tx_hash,
                        "opbnb_timestamp": item.opbnb_timestamp,
                    }
                    for item in paged
                ],
            }

    def stats(self) -> dict:
        """Return global protocol stats."""
        with self._lock:
            total_events = len(self._state.archive)
            total_usd = sum(item.debt_repaid for item in self._state.archive if item.currency == USD)
            total_inr = sum(item.debt_repaid for item in self._state.archive if item.currency == INR)
            total_bnb = sum(item.collateral_seized_bnb for item in self._state.archive)
            return {
                "total_liquidation_events": total_events,
                "total_debt_repaid_usd": str(round(total_usd, 6)),
                "total_debt_repaid_inr": str(round(total_inr, 6)),
                "total_bnb_seized": str(round(total_bnb, 6)),
                "current_bnb_usd_price": str(round(self._state.usd_price / 1e8, 6)),
                "current_bnb_inr_price": str(round(self._state.inr_price / 1e8, 6)),
            }

    def _price_for_position(self, position: Position) -> float:
        """Return relevant BNB price in user currency."""
        if position.currency == INR:
            return self._state.inr_price / 1e8
        return self._state.usd_price / 1e8

    def _position_to_payload(self, position: Position) -> dict:
        """Serialize position into API payload format."""
        bnb_price = self._price_for_position(position)
        collateral_fiat = position.collateral_bnb * bnb_price
        health = position.health_factor(bnb_price)
        return {
            "wallet": position.wallet,
            "collateral_bnb": str(round(position.collateral_bnb, 6)),
            "collateral_fiat": str(round(collateral_fiat, 6)),
            "debt": str(round(position.debt, 6)),
            "health_factor": str(round(health, 6)),
            "is_liquidatable": health < 1.0 and position.debt > 0,
            "currency": position.currency,
            "currency_set": position.currency_set,
        }
