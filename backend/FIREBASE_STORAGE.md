# Firebase (Firestore) storage

When **Firebase is enabled** (`firebase_enabled=true` in config), the following data that is **not** stored on smart contracts is persisted in Firestore. On-chain data (e.g. LendingEngine collateral/debt) remains the source of truth for protocol state; BNPL and user data are stored in Firebase.

## Collections

| Collection | Purpose |
|------------|---------|
| **users** | User profiles: `user_id`, email, phone, full_name, `wallet_address` (list of `{ name, wallet_id }`), notification_channels, currency, loan stats, etc. |
| **bnpl_loans** | BNPL loan records: loan_id, user_id, merchant_id, principal, installments, status, outstanding, etc. |
| **bnpl_collaterals** | Collateral locks per loan (vault_address, deposit_tx_hash, value, etc.). |
| **bnpl_installments** | Installment schedule and payment status per loan. |
| **bnpl_risk_scores** | Risk scores and explainability per loan. |
| **bnpl_liquidation_logs** | Liquidation event logs. |
| **bnpl_events** | Audit trail (COLLATERAL_LOCKED, PLAN_CREATED, etc.). |
| **bnpl_orders** | Order/mandate references. |
| **bnpl_alerts** | Early-warning alerts. |
| **bnpl_settings** | BNPL feature settings. |

Profile collection name is configurable (`firebase_profile_collection`); it is used by `POST /users/from-firebase` to read profile fields (e.g. email, display name) before upserting into **users**.

## How data is written

- **User details and wallets**  
  - `POST /users/from-firebase`: upserts into **users** (create if missing, otherwise update with incoming wallet_address, notification_channels, profile fields).  
  - `PUT /users/{user_id}`: updates existing user document.

- **BNPL loans, collaterals, installments, events**  
  - Written by `BnplFeatureService` via `_set_document()` whenever a plan is created, collateral locked, installments paid, events recorded, etc.  
  - When `firebase_manager` is set, documents go to the collections above; when Firebase is disabled, the same data is kept only in memory (lost on restart).

## How to read

- **User / wallets**: `GET /users/{user_id}`, `GET /users/{user_id}/wallets`.
- **Loans for a user**: `GET /bnpl/loans?user_id=<user_id>` (from **bnpl_loans**).
- **Audit trail**: `GET /bnpl/audit/events` (from **bnpl_events**).
- **Single loan**: safety-meter, proof, explainability, etc. use loan_id and read from the same Firestore collections when Firebase is enabled.

## Configuration

- Enable Firebase and set credentials (e.g. `firebase_credentials_path`, `firebase_project_id`) so that `FirebaseClientManager` and `FirestoreUserRepository` are used.  
- `BnplFeatureService` receives the same `firebase_manager`; when it is not `None`, all BNPL persistence goes to Firestore.
