# API Integration To-Do

Backend base URL: `http://localhost:8000`  
Frontend environment config: `src/environments/environment.ts` → `apiUrl`  
Razorpay SDK: loaded from `https://checkout.razorpay.com/v1/checkout.js` (in `index.html`)  
Razorpay key: `src/environments/environment.ts` → `razorpayKey` (set to your test key)

---

## Legend

| Status | Meaning |
|--------|---------|
| ✅ | Wired and called from UI |
| ⏳ | Partially wired / fallback active |
| ❌ | Not yet wired |

---

## 1. Market APIs

| Method | Endpoint | UI Location | Status | Notes |
|--------|----------|-------------|--------|-------|
| POST | `/market/chart` | `borrow.ts` → `loadBnbChart()` | ✅ | Real BNB price history; fallback to empty chart on error |
| GET | `/market/symbols` | — | ❌ | Not needed yet |
| GET | `/market/resolve` | — | ❌ | Not needed yet |
| GET | `/currency/convert` | — | ❌ | Could be used for INR/USD display |

---

## 2. Risk / ML APIs

| Method | Endpoint | UI Location | Status | Notes |
|--------|----------|-------------|--------|-------|
| POST | `/api/risk/predict` | `borrow.ts` → `loadRiskScore()` | ✅ | Maps `liquidation_probability` → credit score (300–900); fallback on error |
| POST | `/ml/score` | `api.service.ts` (method exists) | ❌ | Alternative scoring; not called from UI |
| POST | `/ml/predict-default` | — | ❌ | Could show "risk of missing next EMI" on board |
| POST | `/ml/recommend-deposit` | — | ❌ | Loan-details uses `GET /bnpl/risk/recommend-deposit/{loan_id}` instead |
| POST | `/ml/orchestrate` | — | ❌ | Multi-model call; useful for combined risk dashboard |
| GET | `/ml/health` | — | ❌ | Health probe before making ML calls |

---

## 3. BNPL APIs

| Method | Endpoint | UI Location | Status | Notes |
|--------|----------|-------------|--------|-------|
| POST | `/bnpl/plans` | `transaction.ts` → `runBnplFlow()` step 1 | ✅ | Creates loan + schedule; returns `loan.id` |
| POST | `/bnpl/collateral/lock` | `transaction.ts` → `runBnplFlow()` step 2 | ✅ | Locks BNB as collateral (vault_address from connected wallet) |
| POST | `/bnpl/users/autopay/mandate` | `transaction.ts` step 3; `loan-details.ts` → `openRazorpay()` | ✅ | Creates Razorpay mandate; then SDK checkout |
| GET | `/bnpl/eligibility/{user_id}` | `borrow.ts` → `loadEligibility()` | ✅ | Drives available credit & `maxBorrow` on borrow page |
| GET | `/bnpl/safety-meter/{loan_id}` | `loan-details.ts` → `loadLoan()` | ✅ | Safety bar / health color on loan-details |
| GET | `/bnpl/risk/recommend-deposit/{loan_id}` | `loan-details.ts` → `loadLoan()` | ✅ | Top-up recommendation (use_ml query) |
| GET | `/bnpl/emi/plans` | `borrow.ts` → `loadEmiPlans()` | ✅ | Installment options (3,4,6,… months); fallback `[3,6,12,24]` |
| GET | `/bnpl/explainability/{loan_id}` | `loan-details.ts` → `loadLoan()` | ✅ | "Why this risk?" reasons list |
| GET | `/bnpl/proof/{loan_id}` | `loan-details.ts` → `loadLoan()` | ✅ | Loan identity, collateral, installments, timeline |
| GET | `/bnpl/payments/razorpay/status` | `transaction.ts` step 4; `loan-details.ts` → `loadRazorpayStatus()` | ✅ | Gate "Pay Now" and checkout; script wait in `api.service` |
| GET | `/bnpl/audit/events` | `board.ts` → `loadBoardData()` | ✅ | History list on board |
| POST | `/bnpl/collateral/topup` | — | ❌ | "Top-up collateral" button on loan-details not wired |
| POST | `/bnpl/alerts/scan` | — | ❌ | Background health warnings |
| PATCH | `/bnpl/users/autopay` | — | ❌ | Toggle autopay on/off in loan-details |
| POST | `/bnpl/disputes/open` | — | ❌ | Dispute button on loan-details |
| POST | `/bnpl/risk/default-nudge` | — | ❌ | Nudge modal when user at risk |
| POST | `/bnpl/disputes/refund` | — | ❌ | Backend only; no UI trigger yet |

---

## 4. Razorpay Payments (via SDK + backend mandate)

| Flow | Triggered From | Backend Endpoint | SDK Action | Status |
|------|---------------|-----------------|------------|--------|
| Pay installment | `loan-details.ts` → "Pay Now" button | `POST /bnpl/users/autopay/mandate` | `openRazorpayCheckout()` after status check | ✅ |
| INR disbursement | `transaction.ts` → step 4 of BNPL flow | `POST /bnpl/users/autopay/mandate` (step 3) | `openRazorpayCheckout()` (step 4) | ✅ |

> **Test-bed**: Set `razorpayKey` in `environment.ts` to your Razorpay test key (`rzp_test_...`).  
> Test card: `4111 1111 1111 1111`, expiry `12/25`, CVV `123`.

---

## 5. Protocol (on-chain simulation) APIs — Solidity contracts

These endpoints simulate or wrap the **contracts in `contracts/src/`**:

| Contract | Role | Backend APIs that map to it |
|----------|------|-----------------------------|
| **LendingEngine.sol** | Collateral deposit/withdraw, borrow, repay, liquidation, account state | `POST /collateral/deposit`, `POST /collateral/withdraw`, `POST /borrow`, `POST /repay`, `POST /liquidate`, `GET /account/{wallet}` |
| **PriceConsumer.sol** | Oracle BNB/USD and BNB/INR prices | `POST /oracle/update-prices`, `GET /oracle/prices` |
| **DebtToken.sol** | pmUSD/pmINR mint/burn/transfer | Used by LendingEngine for borrow/repay |
| **LiquidationArchive.sol** | Liquidation event archive and global stats | `GET /archive/liquidations`, `GET /stats` |

Contract addresses (BSC testnet) are in `backend/config.yml` under `contracts.bsc` (`price_consumer`, `pm_usd`, `pm_inr`; `lending_engine` may be `TBD`). opBNB: `liquidation_archive`.

| Method | Endpoint | UI Location | Status | Notes |
|--------|----------|-------------|--------|-------|
| POST | `/collateral/deposit` | — | ❌ | Mirrors `LendingEngine.depositCollateral()`; chain-level deposit |
| POST | `/collateral/withdraw` | — | ❌ | Mirrors `withdrawCollateral()`; health check before withdraw |
| POST | `/borrow` | — | ❌ | Protocol-level borrow (mirrors `LendingEngine.borrow()`); BNPL flow uses `/bnpl/plans` + `/bnpl/collateral/lock` |
| POST | `/repay` | — | ❌ | Protocol-level repay (mirrors `repay()`) |
| GET | `/account/{wallet}` | — | ❌ | Mirrors `getAccountStatus()`; show on-chain position on board |
| GET | `/stats` | — | ❌ | Mirrors `LiquidationArchive.getGlobalStats()`; protocol stats widget |
| POST | `/liquidate` | — | ❌ | Mirrors `liquidate(address)`; keeper/admin use |
| GET | `/archive/liquidations` | — | ❌ | Paginated liquidation history from LiquidationArchive |
| POST | `/oracle/update-prices` | — | ❌ | Backend/oracle job; mirrors PriceConsumer |
| GET | `/oracle/prices` | — | ❌ | Current BNB/USD and BNB/INR from oracle |

---

## 6. Web3 / Wallet APIs (contract reads & tx history)

These read from the **same Solidity contracts** (LendingEngine, events) or RPC:

| Method | Endpoint | UI Location | Status | Notes |
|--------|----------|-------------|--------|-------|
| GET | `/wallet/validate` | `borrow.ts` → `validateConnectedWallet()` | ✅ | Before submit; checksum in response |
| GET | `/wallet/balance` | `transaction.ts` → `loadWalletBalances()` | ✅ | Per-wallet BNB balance (chain=bsc) |
| GET | `/web3/account/{wallet}` | — | ❌ | On-chain snapshot: collateral, debt, health (getAccountStatus / mapping getters) |
| GET | `/web3/tx-history/{wallet}` | — | ❌ | Solidity events: CollateralDeposited, Borrowed, Repaid, Liquidated |

---

## 7. User & Firebase APIs

| Method | Endpoint | UI Location | Status | Notes |
|--------|----------|-------------|--------|-------|
| POST | `/users/from-firebase` | `get-started.component.ts` → `submit()` via `UsersApiService.createFromFirebase()` | ✅ | Create/update user with wallets & notification_channels on first onboarding |
| GET | `/users/{user_id}/wallets` | `board.ts`, `transaction.ts` → `loadBoardData()` / `loadWallets()` | ✅ | Wallet list for user; balances loaded via `/wallet/balance` |
| GET | `/users/{user_id}` | — | ❌ | Full profile (board user card still uses Firebase Auth only) |
| PUT | `/users/{user_id}` | — | ❌ | Update profile / notification prefs |

---

## 8. Settings

| Method | Endpoint | UI Location | Status | Notes |
|--------|----------|-------------|--------|-------|
| GET | `/settings` | `api.service.ts` → `getSettings()` | ⏳ | Method exists; not called on boot yet; use to gate Razorpay/ML/Web3 features |

---

## 9. Integrations used in UI but outside backend API catalog

| Integration | Used in UI | In API docs? | What to do |
|------------|------------|---------------|------------|
| Firebase Auth | `auth.service.ts`, `login.component.ts`, `get-started.component.ts` | ❌ (not REST) | Keep enabled; authorized domain + Google provider |
| Firestore (`getDoc`/`setDoc`) | `auth.service` (user details) | ❌ | Decide: keep Firestore or migrate to `/users/*` |
| Razorpay Checkout JS SDK | `api.service`, `loan-details`, `transaction` + `index.html` | ❌ (SDK) | Keep script; valid test key; optional backend payment verification |
| Session storage | `borrow`, `transaction`, `board` | ❌ | Local draft state only |

---

## 10. Environment variables / config

| Key | Required | Current status | Purpose |
|-----|----------|----------------|---------|
| `apiUrl` | ✅ | Present | Backend base URL |
| `razorpayKey` | ✅ | Present | Razorpay test key for Checkout SDK |
| `firebase.*` | ✅ | Present | Firebase Auth + Firestore |

Optional: `apiTimeoutMs`, `enableMockFallbacks`, `razorpayEnabled`.

---

## 11. Solidity contracts reference (`contracts/`)

| File | Purpose |
|------|---------|
| **LendingEngine.sol** | Core lending: `depositCollateral`, `withdrawCollateral`, `borrow`, `repay`, `liquidate`, `getAccountStatus`; dual currency (USD/INR via PriceConsumer). |
| **PriceConsumer.sol** | Oracle: BNB/USD and BNB/INR prices (8 decimals). |
| **DebtToken.sol** | ERC-20 style pmUSD/pmINR; mint/burn by LendingEngine. |
| **LiquidationArchive.sol** | Records liquidations; `getGlobalStats()` for protocol stats. |

Backend uses these via `config.yml` → `contracts.bsc` / `contracts.opbnb`. Protocol and Web3 APIs in this doc align with `backend/SOLIDITY_API_DOCUMENTATION.md`.

---

## Quick-start checklist

- [x] Wire `GET /users/{user_id}/wallets` — board & transaction
- [x] Wire `GET /wallet/balance` — transaction wallet list
- [x] Wire `GET /bnpl/eligibility/{user_id}` — borrow page
- [x] Wire `GET /bnpl/safety-meter/{loan_id}` — loan-details
- [x] Wire `GET /bnpl/emi/plans` — borrow installment options
- [x] Wire `GET /bnpl/payments/razorpay/status` — Pay Now + transaction step 4
- [ ] Replace `razorpayKey` in `environment.ts` with your Razorpay test key if needed
- [ ] Start FastAPI backend at `http://localhost:8000` before running UI
- [ ] Call `GET /settings` on app boot to gate Razorpay/ML/Web3 features (optional)
- [ ] Wire `GET /web3/account/{wallet}` and `GET /web3/tx-history/{wallet}` for board/transaction (optional)
- [ ] Wire protocol endpoints (`/account/{wallet}`, `/stats`, `/collateral/deposit`, etc.) if using LendingEngine flows from UI (optional)

---

## Delta (code audit, Feb 2026)

- ✅ `UsersApiService` uses `environment.apiUrl`; `createFromFirebase` used in get-started submit.
- ✅ BNPL, market, risk, wallet, user wallets, and Razorpay flows wired as in tables above.
- ✅ Solidity contracts in `contracts/src/` documented; Protocol/Web3 APIs aligned with `SOLIDITY_API_DOCUMENTATION.md`.
- ⏳ `GET /settings` available in `api.service` but not called on boot.
- ❌ Protocol simulation (`/collateral/deposit`, `/borrow`, `/repay`, `/account/{wallet}`, `/stats`) and Web3 read (`/web3/account/{wallet}`, `/web3/tx-history/{wallet}`) not yet wired in UI.
- ⚠️ Non-REST: Firebase Auth, Firestore, Razorpay JS SDK remain in use by design.
