"""Reusable Web3 client manager for cross-chain read operations."""

import json
import logging
from typing import Any, Dict, Optional

from web3 import Web3


logger = logging.getLogger(__name__)


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
