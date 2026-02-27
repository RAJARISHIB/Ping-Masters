# Solidity Integration API Documentation

## 1) Purpose of this document

This is a **separate Solidity-focused API guide** for Ping-Masters.

It explains:
- Why each Solidity-related API exists.
- Request method and payload schema.
- Response payload schema.
- Which smart-contract behavior it maps to.

This document is scoped to:
- On-chain/protocol simulation APIs.
- Web3 contract-read APIs.
- BNPL APIs that carry Solidity-facing data (vault address, tx hashes, oracle guard, liquidations, proof timelines).

---

## 2) Solidity contracts in this repository

Contracts under `contracts/src`:
- `PriceConsumer.sol`
- `LendingEngine.sol`
- `DebtToken.sol`
- `LiquidationArchive.sol`

Key contract capabilities (high-level):
- Oracle price updates and reads (`PriceConsumer`).
- Collateral deposit/withdraw, borrow/repay, liquidation, account state (`LendingEngine`).
- Debt token mint/burn/transfer (`DebtToken`).
- Liquidation event archival and stats (`LiquidationArchive`).

---

## 3) API groups and Solidity mapping

### 3.1 Direct protocol simulation APIs (`backend/api/router.py`)

These endpoints are backend simulation wrappers for contract-like behaviors.

#### `POST /oracle/update-prices`
- Why used:
  - Updates oracle price snapshots used by borrow capacity, health factor, and liquidation checks.
  - Mirrors `PriceConsumer.updateBothPrices(...)` style behavior.
- Request schema:
  - `usd_price: int` (required, > 0)
  - `inr_price: int` (required, > 0)
- Response schema:
  - `tx_hash: str`
  - `usd_price: int`
  - `inr_price: int`
  - `updated_at: int` (epoch seconds)

#### `GET /oracle/prices`
- Why used:
  - Fetches current oracle values used by all risk/borrow computations.
  - Mirrors `PriceConsumer.getBothPrices()`.
- Request schema:
  - No body/query required.
- Response schema:
  - `usd_price: int`
  - `inr_price: int`
  - `usd_last_updated: int`
  - `inr_last_updated: int`

#### `POST /users/set-currency`
- Why used:
  - Sets borrow currency context (`USD`/`INR`) before debt operations.
  - Mirrors contract currency-selection behavior (`setCurrency` in lending logic).
- Request schema:
  - `wallet: str` (required)
  - `currency: str` (required, expected `USD` or `INR`)
- Response schema:
  - `wallet: str`
  - `currency: str`
  - `tx_hash: str`

#### `POST /collateral/deposit`
- Why used:
  - Adds collateral balance for a wallet before borrowing.
  - Mirrors `depositCollateral()` behavior.
- Request schema:
  - `wallet: str`
  - `amount_bnb: str` (numeric string)
- Response schema:
  - `wallet: str`
  - `deposited_bnb: str`
  - `total_collateral_bnb: str`
  - `tx_hash: str`

#### `POST /collateral/withdraw`
- Why used:
  - Withdraws collateral only if post-withdraw health remains safe.
  - Mirrors `withdrawCollateral(uint256 amount)` checks.
- Request schema:
  - `wallet: str`
  - `amount_bnb: str`
- Response schema:
  - `wallet: str`
  - `withdrawn_bnb: str`
  - `remaining_collateral_bnb: str`
  - `tx_hash: str`

#### `POST /borrow`
- Why used:
  - Borrows debt token against collateral with LTV checks.
  - Mirrors `borrow(uint256 amount)` and `borrow(uint256 amount, Currency currency)`.
- Request schema:
  - `wallet: str`
  - `amount: str`
  - `currency: Optional[str]`
- Response schema:
  - `wallet: str`
  - `borrowed: str`
  - `currency: str`
  - `token: str` (e.g., `pmUSD`, `pmINR`)
  - `health_factor: str`
  - `tx_hash: str`

#### `POST /repay`
- Why used:
  - Reduces outstanding debt and recomputes health.
  - Mirrors `repay(uint256 amount)`.
- Request schema:
  - `wallet: str`
  - `amount: str`
- Response schema:
  - `wallet: str`
  - `repaid: str`
  - `currency: str`
  - `remaining_debt: str`
  - `health_factor: str`
  - `tx_hash: str`

#### `GET /account/{wallet}`
- Why used:
  - Returns a wallet’s collateral/debt/health/liquidatability view.
  - Mirrors `getAccountStatus(address user)`.
- Request schema:
  - Path: `wallet: str`
- Response schema:
  - `wallet: str`
  - `collateral_bnb: str`
  - `collateral_fiat: str`
  - `debt: str`
  - `health_factor: str`
  - `is_liquidatable: bool`
  - `currency: Optional[str]`
  - `currency_set: bool`

#### `GET /positions/all`
- Why used:
  - Lists all known borrower positions (optionally only liquidatable).
  - Operational equivalent of iterating tracked borrowers.
- Request schema:
  - Query: `liquidatable_only: bool = false`
- Response schema:
  - `total: int`
  - `positions: list[ProtocolAccountShape]`

#### `POST /liquidate`
- Why used:
  - Executes liquidation for unhealthy position and archives record.
  - Mirrors `liquidate(address user)` behavior.
- Request schema:
  - `wallet: str`
- Response schema:
  - `borrower: str`
  - `liquidator: str`
  - `debt_repaid: str`
  - `collateral_seized_bnb: str`
  - `bonus_bnb: str`
  - `currency: str`
  - `bsc_tx_hash: str`
  - `opbnb_tx_hash: str`
  - `archive_record_id: int`

#### `GET /archive/liquidations`
- Why used:
  - Reads liquidation ledger/history with pagination.
  - Mirrors `LiquidationArchive` query behavior.
- Request schema:
  - Query:
    - `page: int = 0`
    - `page_size: int = 20`
    - `currency: Optional[str] = None`
- Response schema:
  - `total: int`
  - `page: int`
  - `page_size: int`
  - `records: list[LiquidationRecordShape]`

#### `GET /stats`
- Why used:
  - Returns aggregate liquidation and price stats for protocol monitoring.
  - Mirrors `LiquidationArchive.getGlobalStats()`.
- Request schema:
  - No body/query required.
- Response schema:
  - `total_liquidation_events: int`
  - `total_debt_repaid_usd: str`
  - `total_debt_repaid_inr: str`
  - `total_bnb_seized: str`
  - `current_bnb_usd_price: str`
  - `current_bnb_inr_price: str`

---

### 3.2 Web3 utility and contract read APIs (`backend/api/router.py`)

These endpoints validate addresses, read wallet balances from RPC, and call a configured contract read function on BSC/opBNB.

#### `GET /wallet/validate`
- Why used:
  - Quick client-side/backend validation for EVM wallet IDs.
  - Prevents invalid addresses before contract interactions.
- Request schema:
  - Query: `wallet: str`
- Response schema:
  - `wallet: str`
  - `is_valid: bool`
  - `checksum_address: Optional[str]`

#### `GET /wallet/balance`
- Why used:
  - Reads native balance from selected chain RPC (`bsc`/`opbnb`).
  - Used before collateral deposit/tx routing.
- Request schema:
  - Query:
    - `wallet: str`
    - `chain: str = "bsc"`
- Response schema:
  - `wallet: str` (checksum)
  - `chain: str`
  - `balance_wei: str`
  - `balance_bnb: str`

#### `GET /get-data`
- Why used:
  - Reads configured contract function from both BSC and opBNB contracts.
  - Cross-chain state comparison endpoint.
- Request schema:
  - No payload.
- Response schema:
  - `bsc_testnet_value: Any`
  - `opbnb_testnet_value: Any`
  - `function_name: str`

#### `GET /web3/get-data`
- Why used:
  - Namespaced alias of `/get-data`.
- Request schema:
  - No payload.
- Response schema:
  - Same as `/get-data`.

#### `GET /web3/health`
- Why used:
  - Checks provider connectivity for both configured RPC endpoints.
- Request schema:
  - No payload.
- Response schema:
  - `bsc_connected: bool`
  - `opbnb_connected: bool`

---

### 3.3 BNPL endpoints with Solidity-facing data (`backend/api/bnpl_router.py`)

These APIs are mostly backend orchestration, but include fields that anchor to on-chain state and proof.

#### `POST /bnpl/plans`
- Why used:
  - Creates loan + installment schedule used by collateralized BNPL execution.
- Request schema:
  - `BnplCreatePlanRequest`
  - Main fields:
    - identities: `user_id`, `merchant_id`
    - financial: `principal_minor`, `currency`, `installment_count`, `tenure_days`
    - risk thresholds: `ltv_bps`, `danger_limit_bps`, `liquidation_threshold_bps`
    - fees: `grace_window_hours`, `late_fee_flat_minor`, `late_fee_bps`
    - plan selectors: `emi_plan_id`, `use_plan_defaults`
- Response schema:
  - `loan: dict`
  - `installments: list[dict]`
  - `emi_plan: Optional[dict]`

#### `POST /bnpl/collateral/lock`
- Why used:
  - Records refundable security deposit vault metadata and tx proof.
  - Solidity-facing anchor fields: vault + chain + deposit tx hash.
- Request schema:
  - `loan_id`, `user_id`
  - `asset_symbol`, `deposited_units`, `collateral_value_minor`, `oracle_price_minor`
  - `vault_address`, `chain_id`, `deposit_tx_hash`
  - `proof_page_url: Optional[str]`
- Response schema:
  - `collateral: dict`
  - `safety_meter: dict`

#### `POST /bnpl/collateral/topup`
- Why used:
  - Adds additional collateral to improve health factor.
  - Tracks top-up tx metadata.
- Request schema:
  - `collateral_id`
  - `added_units`, `added_value_minor`, `oracle_price_minor`
  - `topup_tx_hash: Optional[str]`
- Response schema:
  - `collateral: dict`
  - `safety_meter: dict`

#### `GET /bnpl/safety-meter/{loan_id}`
- Why used:
  - Returns collateral-vs-debt health factor for liquidation risk UI.
  - Derived from on-chain style logic.
- Request schema:
  - Path: `loan_id`
- Response schema:
  - `loan_id: str`
  - `collateral_value_minor: int`
  - `outstanding_minor: int`
  - `health_factor: float`
  - `safety_color: str`
  - `danger_limit_bps: int`
  - `liquidation_threshold_bps: int`

#### `POST /bnpl/recovery/partial`
- Why used:
  - Performs partial collateral recovery on missed payments (not full seizure).
  - Admin/liquidator controlled flow.
- Request schema:
  - Headers:
    - `x-admin-role: ADMIN | LIQUIDATOR` (required for authorization)
  - Body:
    - `loan_id`
    - `installment_id`
    - `notes`
    - `merchant_transfer_ref: Optional[str]`
- Response schema:
  - `loan: dict`
  - `installment: dict`
  - `liquidation_log: dict`
  - `merchant_settlement: dict`
  - `remaining_needed_minor: int`

#### `POST /bnpl/merchant/settlements`
- Why used:
  - Merchant-paid-upfront and recovery settlement recording.
  - Can use Razorpay or simulation fallback.
- Request schema:
  - `merchant_id`, `user_id`, `loan_id`, `amount_minor`
  - `external_ref: Optional[str]`
  - `use_razorpay: bool`
- Response schema:
  - settlement/order payload:
    - `order_id`, `merchant_id`, `user_id`, `loan_id`, `amount_minor`
    - `status`, `external_ref`, `provider`
    - `provider_error`, `gateway_payload`
    - `created_at`, `updated_at`, `is_deleted`

#### `GET /bnpl/merchant/risk-view/{loan_id}`
- Why used:
  - Merchant proof view: shows collateral proof artifacts and current safety.
- Request schema:
  - Path: `loan_id`
- Response schema:
  - `loan_id`, `merchant_id`, `user_id`
  - `principal_minor`, `outstanding_minor`
  - `safety_meter: dict`
  - `proof_items: list[{collateral_id, deposit_tx_hash, vault_address, asset_symbol, collateral_value_minor, proof_page_url}]`

#### `GET /bnpl/proof/{loan_id}`
- Why used:
  - Public trust/proof payload for judges/users.
  - Includes contract addresses + tx traces/timeline.
- Request schema:
  - Path: `loan_id`
- Response schema:
  - `loan_id`, `user_id`, `merchant_id`
  - `contract_addresses`:
    - `price_consumer`
    - `opbnb_contract`
  - `collateral_proofs: list[{collateral_id, deposit_tx_hash, vault_address, collateral_value_minor}]`
  - `timeline: list[event]`
  - `safety_meter: dict`

#### `GET /bnpl/oracle/guard`
- Why used:
  - Circuit guard for stale oracle data before risky operations.
- Request schema:
  - Query: `max_age_sec: int = 300`
- Response schema:
  - Either:
    - `healthy: bool`
    - `age_sec: int`
    - `max_age_sec: int`
  - Or:
    - `healthy: false`
    - `reason: str`
    - `age_sec: null`

#### `GET /bnpl/audit/events`
- Why used:
  - Audit trail for state changes and recovery events.
- Request schema:
  - Query: `limit: int = 100` (1..500)
- Response schema:
  - `total: int`
  - `events: list[dict]`

#### `PATCH /bnpl/admin/pause`
- Why used:
  - Emergency pause/circuit breaker for risky actions.
  - Admin-controlled protocol safety.
- Request schema:
  - Headers:
    - `x-admin-role: ADMIN | PAUSER`
    - `x-actor-id: Optional[str]` (default `admin`)
  - Body:
    - `paused: bool`
    - `reason: str`
- Response schema:
  - `paused: bool`
  - `reason: str`
  - `updated_at: datetime`
  - `updated_by: str`
  - `role: str`

---

### 3.4 Risk API tied to liquidation behavior (`backend/api/risk_routes.py`)

#### `POST /api/risk/predict`
- Why used:
  - Estimates liquidation probability for a position.
  - Uses model when available, otherwise fallback heuristic.
- Request schema:
  - `wallet_address: str`
  - `collateral_bnb: Optional[float]`
  - `debt_fiat: Optional[float]`
  - `current_price: Optional[float]`
  - `volatility: float = 0.80`
- Response schema:
  - `wallet_address: str`
  - `prediction`:
    - `liquidation_probability: float`
    - `risk_tier: str`
    - `model_version: str`
  - `current_position`:
    - `collateral_bnb: float`
    - `collateral_value_fiat: float`
    - `debt_fiat: float`
    - `health_factor: float`
    - `ltv: float`
    - `is_liquidatable: bool`
  - `risk_factors`:
    - `distance_to_liquidation_price: float`
    - `liquidation_price: float`
    - `volatility_estimate: float`
    - `borrow_utilization: float`
  - `timestamp: str` (ISO-8601)

---

## 4) Non-Solidity APIs (explicitly out of scope)

The following API groups exist but are not contract-integration APIs:
- User CRUD/profile sync (`/users`, `/users/from-firebase`, `/users/{id}`, `/users/{id}/wallets`, `/firebase/health`)
- Market data and currency conversion (`/market/*`, `/currency/convert`)
- Generic ML training/runtime ops (`/ml/*`, `/risk/recommend-deposit` policy endpoint)

They are documented in:
- `backend/API_DOCUMENTATION.md`

---

## 5) Error/status behavior for Solidity-facing APIs

Common status behavior:
- `200` success
- `400` invalid input/business rule
- `403` invalid admin role headers
- `404` missing wallet/loan/installment
- `409` conflicting protocol state (for example currency change with outstanding debt)
- `422` payload validation error
- `500` internal service error
- `502` upstream provider/RPC failure
- `503` dependency unavailable (Web3/Firebase/ML configuration not active)

Error payload shape:
- `{"detail": "<error message>"}`

---

## 6) Quick integration sequence (recommended)

Typical Solidity-aligned flow:
1. `POST /oracle/update-prices`
2. `POST /users/set-currency`
3. `POST /collateral/deposit`
4. `POST /borrow`
5. `GET /account/{wallet}`
6. `POST /repay` or `POST /liquidate`
7. `GET /archive/liquidations` and `GET /stats`

BNPL + collateral proof flow:
1. `POST /bnpl/plans`
2. `POST /bnpl/collateral/lock`
3. `GET /bnpl/safety-meter/{loan_id}`
4. `POST /bnpl/recovery/partial` (if needed)
5. `GET /bnpl/proof/{loan_id}`

