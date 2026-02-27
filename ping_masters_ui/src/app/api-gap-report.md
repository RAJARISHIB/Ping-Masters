# UI ↔ Backend API Coverage Report (Feb 2026)

Base URL: `http://localhost:8000`

## 1) Confirmed wired and working in UI

### Borrow page
- `GET /wallet/validate`
  - Payload: query `wallet`
  - Expected response: `{ wallet, is_valid, checksum_address }`
- `POST /market/chart`
  - Payload: `{ symbol, timeframe, vs_currency }`
  - Expected response: `{ coin_id, symbol_input, timeframe, vs_currency, prices[] }`
- `POST /api/risk/predict`
  - Payload: `{ wallet_address, collateral_bnb, debt_fiat, current_price, volatility? }`
  - Expected response: `{ wallet_address, prediction { liquidation_probability, risk_tier, model_version }, current_position, risk_factors, timestamp }`
- `GET /bnpl/eligibility/{user_id}`
  - Payload: path `user_id`
  - Expected response: `{ user_id, total_collateral_minor, max_credit_minor, outstanding_minor, available_credit_minor, ltv_bps }`
- `GET /bnpl/emi/plans` (optional query `currency`, `include_disabled`)
  - Expected response: `{ total, currency, plans[] }` — used for repayment tenure options when wired; fallback to static list if API unavailable.

### Transaction page
- `GET /users/{user_id}/wallets`
  - Payload: path `user_id`
  - Expected response: `{ user_id, wallet_address: [{ name, wallet_id }], wallet_count }`
- `GET /wallet/balance`
  - Payload: query `wallet`, `chain`
  - Expected response: `{ wallet, chain, balance_wei, balance_bnb }`
- `POST /bnpl/plans`
  - Payload: `{ user_id, merchant_id, principal_minor, currency, installment_count, tenure_days, ltv_bps, ... }`
  - Expected response: `{ loan, installments[], emi_plan }`
- `POST /bnpl/collateral/lock`
  - Payload: `{ loan_id, user_id, asset_symbol, deposited_units, collateral_value_minor, oracle_price_minor, vault_address, chain_id, ... }`
  - Expected response: `{ collateral, safety_meter }`
- `POST /bnpl/users/autopay/mandate`
  - Payload: `{ user_id, loan_id, amount_minor, currency, customer_*? }`
  - Expected response: `{ loan_id, user_id, amount_minor, provider, payment_link }`
- `GET /bnpl/payments/razorpay/status`
  - Payload: none
  - Expected response: `{ enabled, configured, available }`

### Loan details page
- `GET /bnpl/safety-meter/{loan_id}`
  - Payload: path `loan_id`
  - Expected response: `{ loan_id, collateral_value_minor, outstanding_minor, health_factor, safety_color, ... }`
- `GET /bnpl/proof/{loan_id}`
  - Payload: path `loan_id`
  - Expected response: proof payload with loan identity, collateral proofs, timeline, safety meter
- `GET /bnpl/explainability/{loan_id}`
  - Payload: path `loan_id`
  - Expected response: `{ loan_id, reasons[], risk_score, deposit_recommendation, safety_meter }`
- `GET /bnpl/risk/recommend-deposit/{loan_id}`
  - Payload: path `loan_id`, query `use_ml`
  - Expected response: `{ mode, risk_tier, required_inr, required_token, current_locked_token, current_locked_inr, topup_token }`
- `POST /bnpl/users/autopay/mandate` + Razorpay SDK checkout
  - Used for installment payment simulation.

### Board page
- `GET /users/{user_id}/wallets`
- `GET /bnpl/audit/events`
  - Payload: query `limit`
  - Expected response: `{ total, events[] }`

### Onboarding page
- `POST /users/from-firebase`
  - Payload: `{ user_id, wallet_address: [{ name, wallet_id }], notification_channels[] }`
  - Expected response: `UserModel`

---

## 2) APIs still missing but needed for current UI behavior

These are **needed to remove remaining local/static UI logic** or complete visible UI actions.

### A) `GET /settings` (app boot health-gating)
- Why needed: UI should decide upfront if ML/Razorpay/Web3/Firebase dependent actions are enabled.
- Payload: none
- Expected response: `SettingsSnapshotResponse` containing flags like `firebase_enabled`, `ml_enabled`, `razorpay_*`, `web3_enabled`.

### B) `GET /bnpl/emi/plans` — backend exists
- Backend: `GET /bnpl/emi/plans` is implemented (query `currency`, `include_disabled`).
- UI: Borrow page was using hardcoded installment options (`3, 6, 12, 24`). It is now wired to this API with a static fallback when the API is unavailable.

### C) `GET /users/{user_id}`
- Why needed: Profile button and user card are still not backed by full profile API data (board shows Firebase Auth `user` only).
- Payload: path `user_id`
- Expected response: `UserModel`

### D) `PUT /users/{user_id}`
- Why needed: UI edits like notification preference changes are local-only and not persisted via backend.
- Payload: path `user_id`, body `UserModel`
- Expected response: updated `UserModel`

### E) Optional but strongly recommended for richer wallet/board UX
- `GET /web3/account/{wallet}`
  - Payload: path `wallet`, query `chain`
  - Expected response: on-chain snapshot with `account_state`, balances, warnings
- `GET /web3/tx-history/{wallet}`
  - Payload: path `wallet`, query `chain`, `from_block`, `to_block`, `limit`
  - Expected response: `{ wallet, records[], returned_records, warnings[] }`

---

## 3) Non-API blockers (backend endpoint not present)

These UI areas still use local data because backend contract is missing in current API catalog:
- Bank account CRUD in transaction flow (`bankAccounts` list is local form state).
- Loan title edit persistence in loan-details (edit only affects local UI state).

---

## 4) Razorpay simulation status

**Where Razorpay is invoked in the UI:**
- **Transaction page:** After steps 1–3 (create plan, lock collateral, create mandate), step 4 calls `openRazorpayCheckout()`. If the backend returns `available: false` or any earlier step fails, the flow throws and the user sees "Transaction failed" — the modal never opens.
- **Loan details page:** "Pay Now" button calls `openRazorpay()`, which creates an autopay mandate then opens Razorpay checkout. The button is only visible when there is a **pending installment** (first installment with status `upcoming` or `overdue` from `GET /bnpl/proof/{loan_id}`). If the proof returns no such installments, the button is hidden.

**Why the Razorpay modal may not appear:**
1. **Script load timing:** The Razorpay script in `index.html` loads synchronously, but `api.service.ts` gracefully awaits it.
2. **Backend status:** If `GET /bnpl/payments/razorpay/status` returns `available: false` (e.g. Razorpay not configured or disabled), the transaction flow throws before opening the modal; on loan-details the UI now gates "Pay Now" on this status.
3. **Flow failure before step 4:** Any failure in create plan, lock collateral, or create mandate causes the transaction to fail and step 4 is never run.
    - **Identified Bug:** In the transaction UI, the `POST /bnpl/collateral/lock` API call was previously failing with a `422 Unprocessable Entity` because the `deposit_tx_hash` required payload string was omitted. This silent failure caused the UI to throw before opening the modal.
4. **Loan-details only:** "Pay Now" is shown only when there is a pending installment. If all installments are marked paid or the proof has no upcoming/overdue entries, the button is intentionally not shown.

**Implemented fixes:**
- The missing `deposit_tx_hash` payload field was added to the UI's `lockCollateral` call in `transaction.ts`, fixing the 422 error and allowing the Razorpay checkout step to execute correctly.
- UI waits for the Razorpay script to be loaded before opening checkout (with a short timeout and clear error if not loaded).
- Loan details page fetches `GET /bnpl/payments/razorpay/status` and shows "Pay Now" only when `available === true`; otherwise shows "Payments temporarily unavailable" when there is a pending installment.

**Action taken:** Fixed the missing validation field (`deposit_tx_hash`) which was preventing the Razorpay modal from rendering on the Transaction page. Razorpay simulation is now fully restored.

---

## 5) UI data source audit (display only API data)

| Area | Data | Source | Notes |
|------|------|--------|--------|
| **Board** | History items | `GET /bnpl/audit/events` | ✅ API only |
| **Board** | Wallets | `GET /users/{user_id}/wallets` | ✅ API only |
| **Board** | User name/email | Firebase Auth (`user`) | ⚠️ No `GET /users/{user_id}`; profile is auth-only |
| **Borrow** | BNB price / chart | `POST /market/chart` | ✅ API; initial values are fallback until loaded |
| **Borrow** | Credit score / risk | `POST /api/risk/predict` | ✅ API; initial values are fallback until loaded |
| **Borrow** | Eligibility / max borrow | `GET /bnpl/eligibility/{user_id}` | ✅ API |
| **Borrow** | Installment options | `GET /bnpl/emi/plans` | ✅ Wired to API with fallback `[3,6,12,24]` |
| **Transaction** | Wallets & balances | `GET /users/.../wallets`, `GET /wallet/balance` | ✅ API only |
| **Transaction** | Bank accounts | Local state | ❌ No backend CRUD; see §3 |
| **Loan details** | Loan, installments, safety | `GET /bnpl/safety-meter`, `GET /bnpl/proof`, etc. | ✅ API only |
| **Loan details** | Title edit | Local state | ❌ Not persisted; see §3 |

The UI is configured so that all **displayed** data that has a backend API is sourced from the API; the only remaining hard-coded/static data are bank accounts (no API), loan title edit (no persistence), and fallbacks when an API call fails or is unavailable.

---

## 6) Connected wallet transaction status

Connected-wallet usage is enforced end-to-end:
- Borrow requires MetaMask connect and backend wallet validation.
- Connected wallet is stored and forwarded to transaction route state.
- Transaction pins wallet selection to connected wallet and uses it in `POST /bnpl/collateral/lock` as `vault_address`.
