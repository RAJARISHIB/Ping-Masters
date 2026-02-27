"""Reusable Web3 client manager for cross-chain read operations."""

from datetime import datetime, timezone
from decimal import Decimal
import json
import logging
from typing import Any, Dict, List, Optional, Tuple, Union

from web3 import Web3


logger = logging.getLogger(__name__)

BlockIdentifier = Union[int, str]


class Web3ClientManager:
    """Manage Web3 providers and contract read calls for configured chains."""

    def __init__(
        self,
        bsc_rpc_url: str,
        opbnb_rpc_url: str,
        abi_json: str,
        bsc_contract_address: str,
        opbnb_contract_address: str,
    ) -> None:
        """Initialize provider and contract instances.

        Args:
            bsc_rpc_url: BSC testnet RPC endpoint.
            opbnb_rpc_url: opBNB testnet RPC endpoint.
            abi_json: Contract ABI as JSON string.
            bsc_contract_address: Contract address on BSC testnet.
            opbnb_contract_address: Contract address on opBNB testnet.
        """
        try:
            self._abi = json.loads(abi_json)
            self._bsc_w3 = Web3(Web3.HTTPProvider(bsc_rpc_url))
            self._opbnb_w3 = Web3(Web3.HTTPProvider(opbnb_rpc_url))

            self._bsc_contract = self._bsc_w3.eth.contract(
                address=Web3.to_checksum_address(bsc_contract_address),
                abi=self._abi,
            )
            self._opbnb_contract = self._opbnb_w3.eth.contract(
                address=Web3.to_checksum_address(opbnb_contract_address),
                abi=self._abi,
            )
            logger.info("Web3ClientManager initialized for BSC and opBNB providers.")
        except Exception:
            logger.exception("Failed to initialize Web3ClientManager.")
            raise

    def health(self) -> Dict[str, bool]:
        """Return provider connectivity status for each chain."""
        try:
            return {
                "bsc_connected": bool(self._bsc_w3.is_connected()),
                "opbnb_connected": bool(self._opbnb_w3.is_connected()),
            }
        except Exception:
            logger.exception("Failed to check Web3 provider health.")
            raise

    def read_contract_values(self, function_name: str = "getValue") -> Dict[str, Any]:
        """Read the same contract function from both configured chains.

        Args:
            function_name: Read-only function exposed by the smart contract.

        Returns:
            Dict[str, Any]: Values fetched from BSC and opBNB contract instances.
        """
        try:
            bsc_function = getattr(self._bsc_contract.functions, function_name)
            opbnb_function = getattr(self._opbnb_contract.functions, function_name)
            bsc_val = bsc_function().call()
            opbnb_val = opbnb_function().call()
            return {
                "bsc_testnet_value": bsc_val,
                "opbnb_testnet_value": opbnb_val,
                "function_name": function_name,
            }
        except Exception:
            logger.exception("Failed to call contract function=%s on configured chains.", function_name)
            raise

    def get_wallet_protocol_summary(self, wallet: str, chain: str = "bsc") -> Dict[str, Any]:
        """Return on-chain wallet summary with native balance and debt state.

        The method attempts, in order:
        1. `getAccountStatus(address)` for full position snapshot.
        2. Public mapping getters (`collateralAmount`, `borrowedAmount`, etc.) as fallback.

        Args:
            wallet: EVM wallet address.
            chain: Chain identifier (`bsc` or `opbnb`).

        Returns:
            Dict[str, Any]: Wallet state payload including remaining amount to pay.
        """
        warnings: List[str] = []
        try:
            checksum_wallet = self._normalize_wallet(wallet)
            provider, contract, normalized_chain = self._select_chain(chain)
            balance_wei = int(provider.eth.get_balance(checksum_wallet))
            balance_bnb = self._to_bnb_str(balance_wei)

            account_state: Dict[str, Any] = {
                "source": None,
                "collateral_wei": None,
                "collateral_bnb": None,
                "collateral_fiat_18": None,
                "debt_18": None,
                "remaining_amount_to_pay_18": None,
                "health_factor_raw_1e18": None,
                "health_factor_ratio": None,
                "is_liquidatable": None,
                "currency": None,
                "has_currency": None,
            }

            full_state = self._try_get_account_status(contract=contract, wallet=checksum_wallet)
            if full_state is not None:
                account_state.update(full_state)
            else:
                warnings.append(
                    "Contract function getAccountStatus(address) not available. "
                    "Used fallback mapping getters."
                )
                fallback_state = self._fallback_account_state(contract=contract, wallet=checksum_wallet, warnings=warnings)
                account_state.update(fallback_state)

            return {
                "wallet": checksum_wallet,
                "chain": normalized_chain,
                "contract_address": str(contract.address),
                "native_balance_wei": str(balance_wei),
                "native_balance_bnb": balance_bnb,
                "account_state": account_state,
                "warnings": warnings,
            }
        except Exception:
            logger.exception("Failed fetching wallet protocol summary wallet=%s chain=%s", wallet, chain)
            raise

    def get_wallet_transaction_history(
        self,
        wallet: str,
        chain: str = "bsc",
        from_block: int = 0,
        to_block: BlockIdentifier = "latest",
        limit: int = 200,
    ) -> Dict[str, Any]:
        """Fetch wallet transaction history from contract events.

        Args:
            wallet: EVM wallet address.
            chain: Chain identifier (`bsc` or `opbnb`).
            from_block: Start block (inclusive).
            to_block: End block (`latest` or numeric block).
            limit: Maximum number of records returned (latest-first).

        Returns:
            Dict[str, Any]: Event history payload with transaction hashes and decoded args.
        """
        warnings: List[str] = []
        try:
            if from_block < 0:
                raise ValueError("from_block must be >= 0")
            if limit <= 0 or limit > 1000:
                raise ValueError("limit must be between 1 and 1000")

            checksum_wallet = self._normalize_wallet(wallet)
            provider, contract, normalized_chain = self._select_chain(chain)
            resolved_to_block = self._parse_block_identifier(to_block)

            event_specs = [
                ("CollateralDeposited", {"user": checksum_wallet}, "user"),
                ("CollateralWithdrawn", {"user": checksum_wallet}, "user"),
                ("Borrowed", {"user": checksum_wallet}, "user"),
                ("Repaid", {"user": checksum_wallet}, "user"),
                ("Liquidated", {"user": checksum_wallet}, "borrower"),
                ("Liquidated", {"liquidator": checksum_wallet}, "liquidator"),
            ]

            records: List[Dict[str, Any]] = []
            for event_name, filters, role in event_specs:
                event_entries = self._read_event_entries(
                    contract=contract,
                    event_name=event_name,
                    from_block=from_block,
                    to_block=resolved_to_block,
                    filters=filters,
                    warnings=warnings,
                )
                for item in event_entries:
                    record = self._event_record(item=item, event_name=event_name, role=role)
                    records.append(record)

            deduped_records = self._dedupe_records(records)
            block_timestamps = self._load_block_timestamps(provider=provider, records=deduped_records)

            for record in deduped_records:
                block_no = record.get("block_number")
                timestamp = block_timestamps.get(block_no)
                record["block_timestamp"] = timestamp

            deduped_records.sort(
                key=lambda row: (
                    int(row.get("block_number", 0)),
                    int(row.get("log_index", 0)),
                ),
                reverse=True,
            )
            paged_records = deduped_records[:limit]

            return {
                "wallet": checksum_wallet,
                "chain": normalized_chain,
                "contract_address": str(contract.address),
                "from_block": from_block,
                "to_block": resolved_to_block,
                "total_records": len(deduped_records),
                "returned_records": len(paged_records),
                "records": paged_records,
                "warnings": warnings,
            }
        except Exception:
            logger.exception(
                "Failed fetching wallet transaction history wallet=%s chain=%s from_block=%s to_block=%s",
                wallet,
                chain,
                from_block,
                to_block,
            )
            raise

    def _select_chain(self, chain: str) -> Tuple[Any, Any, str]:
        """Resolve provider/contract by chain name."""
        normalized_chain = str(chain or "").strip().lower()
        if normalized_chain == "bsc":
            return self._bsc_w3, self._bsc_contract, normalized_chain
        if normalized_chain == "opbnb":
            return self._opbnb_w3, self._opbnb_contract, normalized_chain
        raise ValueError("Unsupported chain. Use 'bsc' or 'opbnb'.")

    def _normalize_wallet(self, wallet: str) -> str:
        """Validate and normalize wallet to checksum format."""
        candidate = str(wallet or "").strip()
        if not Web3.is_address(candidate):
            raise ValueError("Invalid wallet address format.")
        return Web3.to_checksum_address(candidate)

    def _parse_block_identifier(self, value: BlockIdentifier) -> BlockIdentifier:
        """Parse and validate block identifier for event queries."""
        if isinstance(value, int):
            if value < 0:
                raise ValueError("Block number must be >= 0")
            return value

        text_value = str(value).strip().lower()
        if text_value.isdigit():
            return int(text_value)

        allowed_tags = {"latest", "earliest", "pending", "safe", "finalized"}
        if text_value in allowed_tags:
            return text_value

        raise ValueError("Invalid to_block value. Use block number or one of: latest, earliest, pending, safe, finalized.")

    def _try_get_account_status(self, contract: Any, wallet: str) -> Optional[Dict[str, Any]]:
        """Attempt full account snapshot using `getAccountStatus`."""
        try:
            fn = getattr(contract.functions, "getAccountStatus", None)
            if fn is None:
                return None
            raw = fn(wallet).call()
            if not isinstance(raw, (list, tuple)) or len(raw) < 6:
                return None

            collateral_wei = int(raw[0])
            collateral_fiat_18 = int(raw[1])
            debt_18 = int(raw[2])
            health_raw = int(raw[3])
            is_liquidatable = bool(raw[4])
            currency_value = raw[5]

            return {
                "source": "getAccountStatus",
                "collateral_wei": str(collateral_wei),
                "collateral_bnb": self._to_bnb_str(collateral_wei),
                "collateral_fiat_18": str(collateral_fiat_18),
                "debt_18": str(debt_18),
                "remaining_amount_to_pay_18": str(debt_18),
                "health_factor_raw_1e18": str(health_raw),
                "health_factor_ratio": self._scaled_to_decimal_str(health_raw, scale=18),
                "is_liquidatable": is_liquidatable,
                "currency": self._map_currency(currency_value),
                "has_currency": None,
            }
        except Exception:
            logger.exception("Failed calling getAccountStatus wallet=%s", wallet)
            return None

    def _fallback_account_state(self, contract: Any, wallet: str, warnings: List[str]) -> Dict[str, Any]:
        """Build account state from optional public mapping getters."""
        result: Dict[str, Any] = {
            "source": "mapping_getters",
            "collateral_wei": None,
            "collateral_bnb": None,
            "collateral_fiat_18": None,
            "debt_18": None,
            "remaining_amount_to_pay_18": None,
            "health_factor_raw_1e18": None,
            "health_factor_ratio": None,
            "is_liquidatable": None,
            "currency": None,
            "has_currency": None,
        }

        try:
            collateral_raw = self._safe_call(contract=contract, function_name="collateralAmount", wallet=wallet)
            if collateral_raw is not None:
                collateral_wei = int(collateral_raw)
                result["collateral_wei"] = str(collateral_wei)
                result["collateral_bnb"] = self._to_bnb_str(collateral_wei)
        except Exception:
            logger.exception("Fallback collateralAmount call failed wallet=%s", wallet)
            warnings.append("Failed reading collateralAmount from contract.")

        try:
            debt_raw = self._safe_call(contract=contract, function_name="borrowedAmount", wallet=wallet)
            if debt_raw is not None:
                debt_18 = int(debt_raw)
                result["debt_18"] = str(debt_18)
                result["remaining_amount_to_pay_18"] = str(debt_18)
        except Exception:
            logger.exception("Fallback borrowedAmount call failed wallet=%s", wallet)
            warnings.append("Failed reading borrowedAmount from contract.")

        try:
            currency_raw = self._safe_call(contract=contract, function_name="userCurrency", wallet=wallet)
            if currency_raw is not None:
                result["currency"] = self._map_currency(currency_raw)
        except Exception:
            logger.exception("Fallback userCurrency call failed wallet=%s", wallet)
            warnings.append("Failed reading userCurrency from contract.")

        try:
            has_currency_raw = self._safe_call(contract=contract, function_name="hasCurrency", wallet=wallet)
            if has_currency_raw is not None:
                result["has_currency"] = bool(has_currency_raw)
        except Exception:
            logger.exception("Fallback hasCurrency call failed wallet=%s", wallet)
            warnings.append("Failed reading hasCurrency from contract.")

        return result

    def _safe_call(self, contract: Any, function_name: str, wallet: str) -> Optional[Any]:
        """Safely call a single-argument read function if available."""
        fn = getattr(contract.functions, function_name, None)
        if fn is None:
            return None
        return fn(wallet).call()

    def _read_event_entries(
        self,
        contract: Any,
        event_name: str,
        from_block: int,
        to_block: BlockIdentifier,
        filters: Dict[str, Any],
        warnings: List[str],
    ) -> List[Any]:
        """Read contract event logs with compatibility fallback for Web3 versions."""
        try:
            event_factory = getattr(contract.events, event_name, None)
            if event_factory is None:
                warnings.append("Event not found in ABI: {0}".format(event_name))
                return []

            event_callable = event_factory()
            try:
                return list(
                    event_callable.get_logs(
                        from_block=from_block,
                        to_block=to_block,
                        argument_filters=filters,
                    )
                )
            except TypeError:
                return list(
                    event_callable.get_logs(
                        fromBlock=from_block,
                        toBlock=to_block,
                        argument_filters=filters,
                    )
                )
            except Exception:
                # Fallback for older providers/clients.
                event_filter = event_callable.create_filter(
                    fromBlock=from_block,
                    toBlock=to_block,
                    argument_filters=filters,
                )
                return list(event_filter.get_all_entries())
        except Exception:
            logger.exception(
                "Failed reading event logs event=%s from_block=%s to_block=%s filters=%s",
                event_name,
                from_block,
                to_block,
                filters,
            )
            warnings.append(
                "Failed reading event {0} with filters {1}".format(event_name, filters)
            )
            return []

    def _event_record(self, item: Any, event_name: str, role: str) -> Dict[str, Any]:
        """Normalize one event log entry into API response schema."""
        try:
            args = dict(getattr(item, "args", {}) or item.get("args", {}))
            tx_hash = self._hex_or_str(getattr(item, "transactionHash", None) or item.get("transactionHash"))
            block_number = int(getattr(item, "blockNumber", None) or item.get("blockNumber") or 0)
            log_index = int(getattr(item, "logIndex", None) or item.get("logIndex") or 0)
            amount_fields = self._extract_amount_fields(event_name=event_name, args=args)

            return {
                "event_name": event_name,
                "role": role,
                "tx_hash": tx_hash,
                "block_number": block_number,
                "log_index": log_index,
                "args": self._normalize_payload(args),
                "amount_fields": amount_fields,
            }
        except Exception:
            logger.exception("Failed normalizing event record event_name=%s", event_name)
            raise

    def _extract_amount_fields(self, event_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Extract common amount fields from event args for easy client use."""
        lower_name = event_name.lower()
        if lower_name in {"collateraldeposited", "collateralwithdrawn", "repaid"}:
            amount = args.get("amount")
            if amount is None:
                return {}
            return {
                "amount_wei_or_18": str(int(amount)),
                "amount_bnb_if_wei": self._to_bnb_str(int(amount)),
            }

        if lower_name == "borrowed":
            amount = args.get("amount")
            currency = args.get("currency")
            if amount is None:
                return {}
            return {
                "amount_18": str(int(amount)),
                "currency": self._map_currency(currency),
            }

        if lower_name == "liquidated":
            debt_repaid = args.get("debtRepaid")
            collateral_seized = args.get("collateralSeized")
            bonus = args.get("bonus")
            return {
                "debt_repaid_18": str(int(debt_repaid)) if debt_repaid is not None else None,
                "collateral_seized_wei": str(int(collateral_seized)) if collateral_seized is not None else None,
                "collateral_seized_bnb": self._to_bnb_str(int(collateral_seized))
                if collateral_seized is not None
                else None,
                "bonus_wei": str(int(bonus)) if bonus is not None else None,
                "bonus_bnb": self._to_bnb_str(int(bonus)) if bonus is not None else None,
                "currency": self._map_currency(args.get("currency")),
            }
        return {}

    def _dedupe_records(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate records based on tx hash + log index + event name."""
        unique: Dict[Tuple[str, int, str], Dict[str, Any]] = {}
        for record in records:
            key = (
                str(record.get("tx_hash") or ""),
                int(record.get("log_index") or 0),
                str(record.get("event_name") or ""),
            )
            unique[key] = record
        return list(unique.values())

    def _load_block_timestamps(self, provider: Any, records: List[Dict[str, Any]]) -> Dict[int, Optional[str]]:
        """Load ISO timestamps for block numbers used in event records."""
        block_numbers = sorted(
            {
                int(item.get("block_number"))
                for item in records
                if item.get("block_number") is not None
            }
        )
        result: Dict[int, Optional[str]] = {}
        for block_number in block_numbers:
            try:
                block = provider.eth.get_block(block_number)
                timestamp_raw = block.get("timestamp")
                if timestamp_raw is None:
                    result[block_number] = None
                    continue
                timestamp_int = int(timestamp_raw)
                result[block_number] = datetime.fromtimestamp(
                    timestamp_int,
                    tz=timezone.utc,
                ).isoformat()
            except Exception:
                logger.exception("Failed reading block timestamp block_number=%s", block_number)
                result[block_number] = None
        return result

    def _map_currency(self, value: Any) -> Optional[str]:
        """Map enum-like chain currency value to readable code."""
        if value is None:
            return None
        try:
            integer_value = int(value)
            if integer_value == 0:
                return "USD"
            if integer_value == 1:
                return "INR"
            return str(integer_value)
        except Exception:
            return str(value)

    def _to_bnb_str(self, wei_value: int) -> str:
        """Convert wei integer to BNB string."""
        return str(Web3.from_wei(int(wei_value), "ether"))

    def _scaled_to_decimal_str(self, raw_value: int, scale: int = 18) -> str:
        """Convert integer with fixed decimals into decimal string."""
        divisor = Decimal(10) ** int(scale)
        return format(Decimal(int(raw_value)) / divisor, "f")

    def _hex_or_str(self, value: Any) -> str:
        """Return hex string for hash-like values."""
        if value is None:
            return ""
        if hasattr(value, "hex"):
            return str(value.hex())
        return str(value)

    def _normalize_payload(self, payload: Any) -> Any:
        """Recursively normalize payload values for JSON response."""
        if isinstance(payload, dict):
            return {str(key): self._normalize_payload(value) for key, value in payload.items()}
        if isinstance(payload, (list, tuple)):
            return [self._normalize_payload(item) for item in payload]
        if hasattr(payload, "hex"):
            return payload.hex()
        if isinstance(payload, Decimal):
            return format(payload, "f")
        return payload
