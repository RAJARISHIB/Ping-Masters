# Ping-Masters API Documentation

> FastAPI backend that bridges the frontend/bot to the on-chain contracts deployed on **BSC Testnet** (lending) and **opBNB Testnet** (liquidation archive).

---

---

## Architecture Overview

```
Frontend / Bot
     │
     ▼
FastAPI Backend  (this API)
     │
     ├─► BSC Testnet (chainId 97)
     │       ├── PriceConsumer.sol   — BNB/USD & BNB/INR oracle
     │       ├── DebtToken.sol (pmUSD)
     │       ├── DebtToken.sol (pmINR)
     │       └── LendingEngine.sol   — borrow / repay / liquidate
     │
     └─► opBNB Testnet (chainId 5611)
             └── LiquidationArchive.sol — permanent liquidation log
```

---

## Currency Values

All endpoints that accept or return a currency use:

| Value | Meaning |
|-------|---------|
| `"USD"` | US Dollar — borrow/repay in pmUSD |
| `"INR"` | Indian Rupee — borrow/repay in pmINR |

Internally these map to the on-chain `PriceConsumer.Currency` enum: `USD = 0`, `INR = 1`.

---

## Endpoints

### 1. Oracle — Update Prices

**`POST /oracle/update-prices`**

Updates both BNB/USD and BNB/INR prices on-chain. Called by the price-feed bot every ~3 seconds.

**Request body:**

```json
{
  "usd_price": 30000000000,
  "inr_price": 2500000000000
}
```

| Field | Type | Description |
|-------|------|-------------|
| `usd_price` | `int` | BNB/USD price with **8 decimal places** (e.g. `30000000000` = $300.00) |
| `inr_price` | `int` | BNB/INR price with **8 decimal places** (e.g. `2500000000000` = ₹25000.00) |

**On-chain call:**

```
PriceConsumer.updateBothPrices(usd_price, inr_price)
```

**Response `200`:**

```json
{
  "tx_hash": "0xabc...",
  "usd_price": 30000000000,
  "inr_price": 2500000000000,
  "updated_at": 1720000000
}
```

**Response `400`:**

```json
{ "detail": "Price must be > 0" }
```

---

### 2. Oracle — Get Current Prices

**`GET /oracle/prices`**

Returns the latest BNB prices stored on-chain.

**Response `200`:**

```json
{
  "usd_price": 30000000000,
  "inr_price": 2500000000000,
  "usd_last_updated": 1720000000,
  "inr_last_updated": 1720000000
}
```

**On-chain call:**

```
PriceConsumer.getBothPrices()
PriceConsumer.lastUpdatedAt(0)   // USD
PriceConsumer.lastUpdatedAt(1)   // INR
```

---

### 3. User — Set Currency Preference

**`POST /users/set-currency`**

Sets the user's preferred debt currency. This is a one-time call before the first borrow. The currency **cannot be changed while the user has outstanding debt**.

**Request body:**

```json
{
  "wallet": "0xUserWalletAddress",
  "currency": "USD"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `wallet` | `string` | User's wallet address |
| `currency` | `"USD"` \| `"INR"` | Preferred debt currency |

**On-chain call (sent from the user's wallet via WalletConnect / MetaMask):**

```
LendingEngine.setCurrency(0)   // USD
LendingEngine.setCurrency(1)   // INR
```

> **Note:** The frontend must sign and send this transaction. The backend can construct the calldata and return it unsigned for the frontend to broadcast.

**Response `200`:**

```json
{
  "wallet": "0xUserWalletAddress",
  "currency": "USD",
  "tx_hash": "0xabc..."
}
```

**Response `409`:**

```json
{ "detail": "Cannot change currency while account has outstanding debt" }
```

---

### 4. Collateral — Deposit

**`POST /collateral/deposit`**

Deposits BNB as collateral. This is a payable transaction sent from the user's wallet.

**Request body:**

```json
{
  "wallet": "0xUserWalletAddress",
  "amount_bnb": "1.5"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `wallet` | `string` | User's wallet address |
| `amount_bnb` | `string` | Amount of BNB to deposit (human-readable, e.g. `"1.5"`) |

**On-chain call:**

```
LendingEngine.depositCollateral{ value: 1.5 BNB }()
```

**Response `200`:**

```json
{
  "wallet": "0xUserWalletAddress",
  "deposited_bnb": "1.5",
  "total_collateral_bnb": "1.5",
  "tx_hash": "0xabc..."
}
```

---

### 5. Collateral — Withdraw

**`POST /collateral/withdraw`**

Withdraws BNB collateral. Reverts on-chain if it would make the position undercollateralised.

**Request body:**

```json
{
  "wallet": "0xUserWalletAddress",
  "amount_bnb": "0.5"
}
```

**On-chain call:**

```
LendingEngine.withdrawCollateral(amount_wei)
```

**Response `200`:**

```json
{
  "wallet": "0xUserWalletAddress",
  "withdrawn_bnb": "0.5",
  "remaining_collateral_bnb": "1.0",
  "tx_hash": "0xabc..."
}
```

**Response `400`:**

```json
{ "detail": "Withdrawal would breach collateral threshold" }
```

---

### 6. Borrow

**`POST /borrow`**

Borrows fiat-pegged tokens (pmUSD or pmINR). On the **first borrow**, the `currency` field atomically sets the user's currency preference and executes the borrow in one transaction. On subsequent borrows, `currency` is optional (the user's stored preference is used).

**Request body (first borrow — sets currency):**

```json
{
  "wallet": "0xUserWalletAddress",
  "amount": "200",
  "currency": "USD"
}
```

**Request body (subsequent borrows):**

```json
{
  "wallet": "0xUserWalletAddress",
  "amount": "50"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `wallet` | `string` | ✅ | User's wallet address |
| `amount` | `string` | ✅ | Amount to borrow in fiat units (e.g. `"200"` = $200 USD or ₹200 INR) |
| `currency` | `"USD"` \| `"INR"` | First borrow only | Sets and locks the currency for this account |

**On-chain calls:**

```
// First borrow (currency specified):
LendingEngine.borrow(200e18, 0)   // 0 = USD

// Subsequent borrows (currency stored on-chain):
LendingEngine.borrow(50e18)
```

**Response `200`:**

```json
{
  "wallet": "0xUserWalletAddress",
  "borrowed": "200",
  "currency": "USD",
  "token": "pmUSD",
  "health_factor": "1.2",
  "tx_hash": "0xabc..."
}
```

**Response `400`:**

```json
{ "detail": "Borrow limit exceeded — max LTV is 75%" }
```

**Response `409`:**

```json
{ "detail": "Cannot change currency while account has outstanding debt" }
```

---

### 7. Repay

**`POST /repay`**

Repays borrowed pmUSD or pmINR. The user must first approve the LendingEngine to spend their debt tokens, or the backend sends a combined `approve + repay` sequence.

**Request body:**

```json
{
  "wallet": "0xUserWalletAddress",
  "amount": "100"
}
```

> The repaid token is always the user's stored currency (pmUSD or pmINR).

**On-chain call:**

```
pmUSD.approve(lendingEngineAddress, 100e18)  // or pmINR
LendingEngine.repay(100e18)
```

**Response `200`:**

```json
{
  "wallet": "0xUserWalletAddress",
  "repaid": "100",
  "currency": "USD",
  "remaining_debt": "100",
  "health_factor": "2.4",
  "tx_hash": "0xabc..."
}
```

---

### 8. Account Status

**`GET /account/{wallet}`**

Returns the full on-chain position for a wallet.

**Path parameter:**

| Param | Description |
|-------|-------------|
| `wallet` | User's wallet address |

**On-chain call:**

```
LendingEngine.getAccountStatus(wallet)
```

**Response `200`:**

```json
{
  "wallet": "0xUserWalletAddress",
  "collateral_bnb": "1.0",
  "collateral_fiat": "300.0",
  "debt": "200.0",
  "health_factor": "1.2",
  "is_liquidatable": false,
  "currency": "USD",
  "currency_set": true
}
```

| Field | Description |
|-------|-------------|
| `collateral_bnb` | BNB deposited (human-readable) |
| `collateral_fiat` | BNB value in the user's chosen fiat (USD or INR) |
| `debt` | Outstanding debt in fiat |
| `health_factor` | `>= 1.0` is safe; `< 1.0` is liquidatable |
| `is_liquidatable` | Convenience boolean |
| `currency` | `"USD"` or `"INR"` — `null` if not yet set |
| `currency_set` | `false` if the user has never borrowed |

---

### 9. All Positions (Monitoring)

**`GET /positions/all`**

Returns account status for every address that has ever deposited or borrowed. The liquidation bot polls this endpoint every ~3 seconds to find undercollateralised accounts.

**Query parameters:**

| Param | Default | Description |
|-------|---------|-------------|
| `liquidatable_only` | `false` | If `true`, return only accounts where `is_liquidatable = true` |

**Response `200`:**

```json
{
  "total": 42,
  "positions": [
    {
      "wallet": "0xAlice...",
      "collateral_bnb": "1.0",
      "collateral_fiat": "300.0",
      "debt": "225.0",
      "health_factor": "1.0667",
      "is_liquidatable": false,
      "currency": "USD"
    },
    {
      "wallet": "0xBob...",
      "collateral_bnb": "1.0",
      "collateral_fiat": "200.0",
      "debt": "225.0",
      "health_factor": "0.711",
      "is_liquidatable": true,
      "currency": "USD"
    }
  ]
}
```

> The list of tracked wallets is maintained by indexing `CollateralDeposited` and `Borrowed` events from LendingEngine.

---

### 10. Liquidate

**`POST /liquidate`**

Liquidates an undercollateralised position. The bot calls this after detecting `is_liquidatable = true`. The operation executes on BSC, then cross-posts the event to opBNB's LiquidationArchive.

**Request body:**

```json
{
  "wallet": "0xBorrowerAddress"
}
```

**On-chain sequence:**

```
// Step 1 — BSC Testnet
pmUSD.approve(lendingEngineAddress, debtAmount)   // bot must hold pmUSD/pmINR
LendingEngine.liquidate(borrowerAddress)

// Step 2 — opBNB Testnet (cross-chain log)
LiquidationArchive.logLiquidation(
  borrower, liquidatorBot,
  debtRepaid, collateralSeized, bonusSeized,
  currency,          // 0 = USD, 1 = INR (read from BSC event)
  bscBlockNumber,
  bscTxHash
)
```

**Response `200`:**

```json
{
  "borrower": "0xBorrowerAddress",
  "liquidator": "0xBotAddress",
  "debt_repaid": "225.0",
  "collateral_seized_bnb": "1.18125",
  "bonus_bnb": "0.05625",
  "currency": "USD",
  "bsc_tx_hash": "0xabc...",
  "opbnb_tx_hash": "0xdef...",
  "archive_record_id": 7
}
```

**Response `400`:**

```json
{ "detail": "Position is healthy — cannot liquidate" }
```

---

### 11. Liquidation Archive — All Records

**`GET /archive/liquidations`**

Returns paginated liquidation history from opBNB's LiquidationArchive.

**Query parameters:**

| Param | Default | Description |
|-------|---------|-------------|
| `page` | `0` | Zero-based page index |
| `page_size` | `20` | Records per page (max 100) |
| `currency` | _(all)_ | Filter by `"USD"` or `"INR"` |

**On-chain call:**

```
LiquidationArchive.getLiquidation(id)     // per record
LiquidationArchive.totalLiquidations()    // total count
```

**Response `200`:**

```json
{
  "total": 15,
  "page": 0,
  "page_size": 20,
  "records": [
    {
      "id": 0,
      "borrower": "0xAlice...",
      "liquidator": "0xBot...",
      "debt_repaid": "225.0",
      "collateral_seized_bnb": "1.18125",
      "bonus_bnb": "0.05625",
      "currency": "USD",
      "bsc_block": 10000000,
      "bsc_tx_hash": "0xabc...",
      "opbnb_timestamp": 1720000000
    }
  ]
}
```

---

### 12. Global Stats

**`GET /stats`**

Returns aggregate protocol statistics from both BSC and opBNB.

**On-chain calls:**

```
LiquidationArchive.getGlobalStats()
  → (totalEvents, totalUSD, totalINR, totalBNBSeized)
```

**Response `200`:**

```json
{
  "total_liquidation_events": 15,
  "total_debt_repaid_usd": "3375.0",
  "total_debt_repaid_inr": "270000.0",
  "total_bnb_seized": "17.71875",
  "current_bnb_usd_price": "300.0",
  "current_bnb_inr_price": "25000.0"
}
```

---

## Background Services (Bots)

### Price Feed Bot

Runs as a background task every **3 seconds**:

1. Fetch BNB/USD and BNB/INR from a CEX (e.g. Binance) or aggregator.
2. `POST /oracle/update-prices` with the fresh prices.
3. The API calls `PriceConsumer.updateBothPrices(usdPrice, inrPrice)` on-chain.

### Health Monitor + Liquidation Bot

Runs every **3 seconds**:

1. `GET /positions/all?liquidatable_only=true`
2. For each position where `is_liquidatable = true`:
   a. Check the bot holds enough pmUSD/pmINR to cover the debt.
   b. `POST /liquidate` with the borrower's wallet.
3. Retry with exponential backoff on transaction failures.

---

## Error Codes

| HTTP | Meaning |
|------|---------|
| `200` | Success |
| `400` | Bad request / on-chain revert |
| `404` | Wallet not found / no position |
| `409` | State conflict (currency locked, minter already set) |
| `422` | Validation error (invalid address, negative amount) |
| `500` | RPC error / node unavailable |

---

## On-Chain Contract Addresses

Populated after deployment — see `contracts/deployments/`:

| Contract | Network | Address |
|----------|---------|---------|
| PriceConsumer | BSC Testnet | 0xB224d6981F6E02Fb0A848f2366B406edbAd3B755 |
| DebtToken (pmUSD) | BSC Testnet | 0x43cc472cA4fe4027aA583871fE8F7Bb683B82279 |
| DebtToken (pmINR) | BSC Testnet | 0x55ff535cbf9Dc439Ea3D610097bfA8f1D0b0F332 |
| LendingEngine | BSC Testnet | TBD |
| LiquidationArchive | opBNB Testnet | 0x937760A01819B6889453eaf8F03E5C3Cf7423278 |

---

## Decimal Conventions

| Value | On-chain unit | Human-readable |
|-------|--------------|----------------|
| BNB collateral | Wei (1e18) | Divide by 1e18 |
| Debt (pmUSD / pmINR) | 1e18 per fiat unit | Divide by 1e18 |
| Oracle price | 8 decimals | Divide by 1e8 |
| Health factor | 1e18 = 1.0 | Divide by 1e18 |

---

## ML Operations API (Payload, Training, Runtime)

### `GET /ml/payload-specs`
Returns required and optional fields for:
- `risk` score payload
- `default` prediction payload
- `deposit` recommendation payload

### `POST /ml/payload-analyze`
Checks payload completeness and normalization readiness before inference/training.

Request:
```json
{
  "model_type": "default",
  "payload": {
    "on_time_ratio": 0.82,
    "missed_count_90d": 1
  }
}
```

### `POST /ml/payload-build-training-row`
Builds a normalized training row from raw payload.

Request:
```json
{
  "model_type": "risk",
  "payload": {
    "plan_amount_inr": 5000,
    "tenure_days": 60,
    "installment_count": 4,
    "outstanding_debt_inr": 4800,
    "collateral_value_inr": 7200
  },
  "label": "MEDIUM"
}
```

### `GET /ml/training/specs`
Returns model feature columns, label columns, artifact paths, and default thresholds.

### `POST /ml/training/generate-dataset`
Generates synthetic dataset CSV for `risk` / `default` / `deposit`.

Request:
```json
{
  "model_type": "deposit",
  "rows": 10000,
  "seed": 42
}
```

### `POST /ml/training/train`
Trains selected model from provided dataset path or synthetic data.

Request:
```json
{
  "model_type": "default",
  "data_path": "backend/ml/artifacts/default_training_data.csv",
  "reload_after_train": true,
  "high_threshold": 0.6,
  "medium_threshold": 0.3
}
```

### `POST /ml/runtime/reload`
Reloads one or more model artifacts without restarting backend.

Request:
```json
{
  "reload_risk": true,
  "reload_default": true,
  "reload_deposit": true
}
```

### `PATCH /ml/runtime/default-thresholds`
Updates default prediction tier thresholds at runtime.

Request:
```json
{
  "high_threshold": 0.65,
  "medium_threshold": 0.35
}
```
