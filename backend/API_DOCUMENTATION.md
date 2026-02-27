# Ping-Masters Backend API Documentation

## 1) What this repository is for

This backend powers a **Web3 collateralized lending + BNPL hackathon product**.

Core responsibilities:
- Serve REST APIs for wallet, lending, BNPL, ML risk scoring, and operational status.
- Simulate protocol operations (`borrow`, `repay`, `liquidate`) in an in-memory service.
- Store user and BNPL documents in Firestore (when Firebase is configured).
- Integrate market data, currency conversion, Web3 contract reads, and Razorpay test flows.
- Run ML workflows for:
  - risk tier scoring,
  - default prediction,
  - deposit recommendation,
  - cross-EMI-plan evaluation.

## 2) Runtime API surfaces

`backend/main.py` mounts:
- `build_router(settings)` from `backend/api/router.py`
- `build_risk_router()` from `backend/api/risk_routes.py`

Additional note:
- `backend/api/routes.py` is only a compatibility export and does not define separate endpoints.

Total active endpoints in repo: **130+** (including BNPL enterprise extension APIs)

## 3) Common response and error conventions

Common success type:
- JSON object (`dict`) or typed model (`response_model=...`)

Common error type:
- `{"detail": "<message>"}` from FastAPI `HTTPException`

Typical status codes:
- `200` success
- `201` created
- `400` bad request / invalid business rule
- `403` role/permission failure
- `404` record not found
- `409` conflict/version or business conflict
- `422` request validation error
- `500` internal server error
- `502` upstream provider/network failure
- `503` dependency unavailable

---

## 4) Request payload schema catalog

### 4.1 Core router request models

`MarketChartRequest`
- `symbol: str`
- `timeframe: str` (e.g. `1D`, `7D`, `30D`, `1Y`)
- `vs_currency: str = "usd"`

`OracleUpdatePricesRequest`
- `usd_price: int > 0`
- `inr_price: int > 0`

`UserSetCurrencyRequest`
- `wallet: str`
- `currency: str` (`USD` or `INR`)

`CollateralRequest`
- `wallet: str`
- `amount_bnb: str`

`BorrowRequest`
- `wallet: str`
- `amount: str`
- `currency: Optional[str]`

`RepayRequest`
- `wallet: str`
- `amount: str`

`LiquidateRequest`
- `wallet: str`

`UserFromFirebaseCreateRequest`
- `user_id: str`
- `wallet_address: list[WalletAddressModel]`
- `notification_channels: list[str]`
- `currency_code: str = "INR"`
- `currency_symbol: str = "Rs"`
- `autopay_enabled: bool = false`
- `kyc_level: int = 0`

`UserModel` (used by create/update user APIs)
- `user_id, email, phone, full_name`
- `currency_code, currency_symbol`
- `autopay_enabled, notification_channels`
- `status, kyc_level`
- `wallet_address: list[WalletAddressModel]`
- behavior counters and loan summary fields

`WalletAddressModel`
- `name: str`
- `wallet_id: str`

### 4.2 ML request models

`RiskFeatureInput` (`POST /ml/score`)
- `safety_ratio`
- `missed_payment_count`
- `on_time_ratio`
- `avg_delay_hours`
- `topup_count_last_30d`
- `plan_amount`
- `tenure_days`
- `installment_amount`

`DepositRecommendationRequest` (`/risk/recommend-deposit`, `/ml/recommend-deposit`)
- `plan_amount_inr`
- `tenure_days`
- `risk_tier`
- `collateral_token`
- `collateral_type` (`stable`/`volatile`)
- `locked_token`
- `price_inr`
- `stress_drop_pct` (optional)
- `fees_buffer_pct` (optional)
- `outstanding_debt_inr` (optional)

`DefaultPredictionInput` (`POST /ml/predict-default`)
- Identity/context: `user_id`, `plan_id`, `installment_id`, `cutoff_at`
- Repayment behavior:
  - `on_time_ratio`
  - `missed_count_90d`
  - `max_days_late_180d`
  - `avg_days_late`
  - `days_since_last_late`
  - `consecutive_on_time_count`
- Plan context:
  - `plan_amount`
  - `tenure_days`
  - `installment_amount`
  - `installment_number`
  - `days_until_due`
- Collateral/risk:
  - `current_safety_ratio`
  - `distance_to_liquidation_threshold`
  - `collateral_type`
  - `collateral_volatility_bucket`
  - `topup_count_30d`
  - `topup_recency_days`
- Engagement:
  - `opened_app_last_7d`
  - `clicked_pay_now_last_7d`
  - `payment_attempt_failed_count`
- Wallet activity:
  - `wallet_age_days`
  - `tx_count_30d`
  - `stablecoin_balance_bucket`

`MlPayloadAnalysisRequest`
- `model_type: "risk" | "default" | "deposit"`
- `payload: dict`

`MlTrainingRowBuildRequest`
- `model_type: "risk" | "default" | "deposit"`
- `payload: dict`
- `label: Optional[Any]`

`MlGenerateDatasetRequest`
- `model_type`
- `rows`
- `seed`
- `output_path` (optional)

`MlTrainModelRequest`
- `model_type`
- `data_path` (optional)
- `rows`
- `seed`
- `output_path` (optional)
- `auto_generate_if_missing`
- `reload_after_train`
- `high_threshold` (optional)
- `medium_threshold` (optional)

`MlReloadModelsRequest`
- `reload_risk`
- `reload_default`
- `reload_deposit`
- `risk_model_path` (optional)
- `default_model_path` (optional)
- `deposit_model_path` (optional)

`MlUpdateDefaultThresholdRequest`
- `high_threshold`
- `medium_threshold`

`MlOrchestrationRequest`
- `risk_payload: Optional[dict]`
- `default_payload: Optional[dict]`
- `deposit_payload: Optional[dict]`
- `run_policy_deposit: bool`
- `run_ml_deposit: bool`
- `include_normalized_payload: bool`

`MlEmiPlanEvaluationRequest`
- `base_payload: dict`
- `plan_ids: Optional[list[str]]`
- `run_risk: bool`
- `run_default: bool`
- `run_policy_deposit: bool`
- `run_ml_deposit: bool`
- `include_normalized_payload: bool`

### 4.3 BNPL request models

`BnplCreatePlanRequest`
- `user_id, merchant_id, principal_minor, currency`
- `installment_count, tenure_days`
- `ltv_bps, danger_limit_bps, liquidation_threshold_bps`
- `grace_window_hours, late_fee_flat_minor, late_fee_bps`
- `emi_plan_id` (optional)
- `use_plan_defaults` (bool)

`BnplLockDepositRequest`
- `loan_id, user_id, asset_symbol`
- `deposited_units, collateral_value_minor, oracle_price_minor`
- `vault_address, chain_id, deposit_tx_hash`
- `proof_page_url` (optional)

`BnplTopUpRequest`
- `collateral_id, added_units, added_value_minor, oracle_price_minor`
- `topup_tx_hash` (optional)

`BnplAutopayRequest`
- `user_id`
- `enabled`

`BnplAutopayMandateRequest`
- `user_id, loan_id, amount_minor, currency`
- `customer_name` (optional)
- `customer_email` (optional)
- `customer_contact` (optional)

`BnplDisputeRequest`
- `loan_id`
- `reason`

`BnplDisputeResolveRequest`
- `loan_id`
- `resolution`
- `restore_active`
- `refund_payment_id` (optional)
- `refund_amount_minor` (optional)

`BnplDisputeRefundRequest`
- `loan_id`
- `payment_id`
- `amount_minor` (optional)
- `notes`

`BnplMissedSimulationRequest`
- `loan_id`
- `installment_id`

`BnplPartialRecoveryRequest`
- `loan_id`
- `installment_id`
- `notes`
- `merchant_transfer_ref` (optional)

`BnplMerchantSettlementRequest`
- `merchant_id`
- `user_id`
- `loan_id`
- `amount_minor`
- `external_ref` (optional)
- `use_razorpay`

`BnplAdminPauseRequest`
- `paused`
- `reason`

### 4.4 Risk v2 request model

`RiskPredictRequest` (`POST /api/risk/predict`)
- `wallet_address: str`
- `collateral_bnb: Optional[float]`
- `debt_fiat: Optional[float]`
- `current_price: Optional[float]`
- `volatility: float = 0.80`

---

## 5) Response payload schema catalog (named shapes used below)

`RootMessageResponse`
- `message: str`

`HealthResponse`
- `status: "ok"`

`WalletValidationResponse`
- `wallet`
- `is_valid`
- `checksum_address`

`WalletBalanceResponse`
- `wallet`
- `chain`
- `balance_wei`
- `balance_bnb`

`MarketChartResponse`
- `coin_id, symbol_input, timeframe, vs_currency, points`
- `prices`
- optional: `market_caps`, `total_volumes`, `provider`, `note`

`MarketSymbolsResponse`
- `total`
- `symbols: list[{id, symbol, name}]`
- `provider`

`MarketResolveResponse`
- `input`
- `coin_id`
- `provider`

`CurrencyConvertResponse` (from `common.convert_currency_amount`)
- `amount`
- `from_currency`
- `to_currency`
- `converted_amount`
- `rate`
- `provider`

`SettingsSnapshotResponse`
- `app_name, debug, host, port`
- feature flags and config pointers (`firebase_enabled`, `web3_enabled`, `ml_enabled`, `emi_*`, `razorpay_*`)

`MlHealthResponse`
- `ml_enabled`
- model loaded/path flags

`MlSpecsResponse`
- model payload field definitions and EMI plan mini-catalog

`MlPayloadAnalysisResponse`
- `model_type`
- required/optional fields
- completeness and normalization report
- optional validation errors

`MlTrainingRowBuildResponse`
- `model_type`
- `row` (normalized training row)

`MlRuntimeStatusResponse`
- `enabled`
- runtime states for risk/default/deposit models

`MlTrainingSpecsResponse`
- dataset paths, feature columns, label names, artifact paths

`MlGenerateDatasetResponse`
- `model_type`
- `rows`
- `output_path`

`MlTrainModelResponse`
- `model_type`
- `summary`
- `runtime`

`MlReloadResponse`
- `results`
- `runtime`

`MlThresholdUpdateResponse`
- updated thresholds + runtime apply flag

`MlScoreResponse`
- `risk_tier`
- `probabilities`
- `top_reasons`
- `model_name`, `model_version`

`DefaultPredictionResponse`
- `user_id, plan_id, installment_id`
- `p_miss_next`
- `tier`
- `thresholds`
- `actions`
- `top_reasons`
- `model_name`, `model_version`

`DepositRecommendationResponse`
- `mode`
- `risk_tier`
- `required_inr`
- `required_token`
- `current_locked_token`
- `current_locked_inr`
- `topup_token`
- optional model metadata

`MlOrchestrationResponse`
- `success`
- `results`
- `errors`

`MlEmiEvaluationResponse`
- `success`
- `total_plans`
- `evaluations[]` per plan with nested `results/errors`

`ProtocolPriceUpdateResponse`
- `tx_hash`
- `usd_price`
- `inr_price`
- `updated_at`

`ProtocolPriceReadResponse`
- `usd_price`
- `inr_price`
- `usd_last_updated`
- `inr_last_updated`

`ProtocolSetCurrencyResponse`
- `wallet`
- `currency`
- `tx_hash`

`ProtocolCollateralDepositResponse`
- `wallet`
- `deposited_bnb`
- `total_collateral_bnb`
- `tx_hash`

`ProtocolCollateralWithdrawResponse`
- `wallet`
- `withdrawn_bnb`
- `remaining_collateral_bnb`
- `tx_hash`

`ProtocolBorrowResponse`
- `wallet`
- `borrowed`
- `currency`
- `token`
- `health_factor`
- `tx_hash`

`ProtocolRepayResponse`
- `wallet`
- `repaid`
- `currency`
- `remaining_debt`
- `health_factor`
- `tx_hash`

`ProtocolAccountResponse`
- `wallet`
- `collateral_bnb`
- `collateral_fiat`
- `debt`
- `health_factor`
- `is_liquidatable`
- `currency`
- `currency_set`

`ProtocolPositionsResponse`
- `total`
- `positions[]` (`ProtocolAccountResponse`)

`ProtocolLiquidateResponse`
- `borrower`
- `liquidator`
- `debt_repaid`
- `collateral_seized_bnb`
- `bonus_bnb`
- `currency`
- `bsc_tx_hash`
- `opbnb_tx_hash`
- `archive_record_id`

`ProtocolArchiveResponse`
- `total`
- `page`
- `page_size`
- `records[]`

`ProtocolStatsResponse`
- `total_liquidation_events`
- `total_debt_repaid_usd`
- `total_debt_repaid_inr`
- `total_bnb_seized`
- `current_bnb_usd_price`
- `current_bnb_inr_price`

`UserWalletDetailsResponse`
- `user_id`
- `wallet_address: list[WalletAddressModel]`
- `wallet_count`

`FirebaseHealthResponse`
- `status`

`Web3ReadResponse`
- `bsc_testnet_value`
- `opbnb_testnet_value`
- `function_name`

`Web3HealthResponse`
- `bsc_connected`
- `opbnb_connected`

`Web3AccountSnapshotResponse`
- `wallet`
- `chain`
- `contract_address`
- `native_balance_wei`
- `native_balance_bnb`
- `account_state`
  - `source`
  - `collateral_wei`
  - `collateral_bnb`
  - `collateral_fiat_18`
  - `debt_18`
  - `remaining_amount_to_pay_18`
  - `health_factor_raw_1e18`
  - `health_factor_ratio`
  - `is_liquidatable`
  - `currency`
  - `has_currency`
- `warnings[]`

`Web3TxHistoryResponse`
- `wallet`
- `chain`
- `contract_address`
- `from_block`
- `to_block`
- `total_records`
- `returned_records`
- `records[]`
  - `event_name`
  - `role`
  - `tx_hash`
  - `block_number`
  - `log_index`
  - `block_timestamp`
  - `args`
  - `amount_fields`
- `warnings[]`

`BnplFeatureStatusResponse`
- `implemented[]`
- `razorpay_enabled_features[]`

`BnplEmiPlansResponse`
- `total`
- `currency`
- `plans[]`

`BnplRazorpayFeatureMapResponse`
- provider metadata + feature list

`BnplRazorpayStatusResponse`
- `enabled`
- `configured`
- `available`

`BnplPlanCreateResponse`
- `loan`
- `installments[]`
- `emi_plan`

`BnplCollateralMutationResponse`
- `collateral`
- `safety_meter`

`BnplSafetyMeterResponse`
- `loan_id`
- `collateral_value_minor`
- `outstanding_minor`
- `health_factor`
- `safety_color`
- thresholds

`BnplAlertsScanResponse`
- `alerts_created`
- `alerts[]`

`BnplEligibilityResponse`
- `user_id`
- `total_collateral_minor`
- `max_credit_minor`
- `outstanding_minor`
- `available_credit_minor`
- `ltv_bps`

`BnplAutopayToggleResponse`
- `user_id`
- `autopay_enabled`

`BnplAutopayMandateResponse`
- `loan_id`
- `user_id`
- `amount_minor`
- `provider`
- `payment_link`

`BnplDisputeOpenResponse`
- `loan`
- `reason`

`BnplDisputeResolveResponse`
- `loan`
- `resolution`
- `refund` (optional)

`BnplDisputeRefundResponse`
- `loan_id`
- `payment_id`
- `provider`
- `refund`

`BnplLateFeePreviewResponse`
- `loan_id`
- `installment_id`
- `due_at`
- `grace_deadline`
- `in_grace`
- fee fields

`BnplMissedSimulationResponse`
- `loan_id`
- `installment_id`
- `missed_amount_minor`
- `penalty_minor`
- `needed_minor`
- `available_collateral_minor`
- `seized_minor_if_default`
- `remaining_collateral_minor`

`BnplPartialRecoveryResponse`
- `loan`
- `installment`
- `liquidation_log`
- `merchant_settlement`
- `remaining_needed_minor`

`BnplMerchantSettlementResponse`
- settlement order payload with `order_id`, `merchant_id`, `loan_id`, `amount_minor`, `provider`, timestamps

`BnplMerchantDashboardResponse`
- `merchant_id`
- totals and status breakdown
- `loans[]`
- `orders[]`

`BnplMerchantRiskViewResponse`
- `loan_id, merchant_id, user_id`
- financial summary
- `safety_meter`
- `proof_items[]`

`BnplRiskScoreResponse`
- risk score snapshot fields from `RiskScoreModel`

`BnplDefaultNudgeResponse`
- `prediction`
- `nudge`

`BnplExplainabilityResponse`
- `loan_id`
- `reasons[]`
- `risk_score`
- `deposit_recommendation`
- `safety_meter`

`BnplProofResponse`
- loan identity
- contract addresses
- collateral proofs
- timeline
- safety meter

`BnplOracleGuardResponse`
- `healthy`
- `age_sec`
- `max_age_sec` or reason

`BnplAuditEventsResponse`
- `total`
- `events[]`

`BnplAdminPauseResponse`
- `paused`
- `reason`
- `updated_at`
- `updated_by`
- `role`

`RiskPredictResponse` (`/api/risk/predict`)
- `wallet_address`
- `prediction`:
  - `liquidation_probability`
  - `risk_tier`
  - `model_version`
- `current_position`
- `risk_factors`
- `timestamp`

---

## 6) Complete endpoint catalog (every API in this repo)

### 6.1 Core, market, wallet, settings

| Method | Path | Use | Request payload schema | Response payload schema |
|---|---|---|---|---|
| GET | `/` | Service root ping | None | `RootMessageResponse` |
| GET | `/health` | App health probe | None | `HealthResponse` |
| GET | `/wallet/validate` | Validate EVM wallet format | Query: `wallet` | `WalletValidationResponse` |
| GET | `/wallet/balance` | Read native chain balance | Query: `wallet`, `chain` (`bsc/opbnb`) | `WalletBalanceResponse` |
| POST | `/market/chart` | Symbol/timeframe chart data | Body: `MarketChartRequest` | `MarketChartResponse` |
| GET | `/market/symbols` | List provider symbols | Query: `refresh: bool` | `MarketSymbolsResponse` |
| GET | `/market/resolve` | Resolve symbol to provider id | Query: `symbol` | `MarketResolveResponse` |
| GET | `/currency/convert` | Currency conversion | Query: `amount`, `from_currency`, `to_currency` | `CurrencyConvertResponse` |
| GET | `/settings` | Runtime settings snapshot | None | `SettingsSnapshotResponse` |

### 6.2 ML APIs

| Method | Path | Use | Request payload schema | Response payload schema |
|---|---|---|---|---|
| GET | `/ml/health` | Risk model health | None | `MlHealthResponse` |
| GET | `/ml/payload-specs` | ML payload field contracts | None | `MlSpecsResponse` |
| POST | `/ml/payload-analyze` | Payload completeness and normalization audit | Body: `MlPayloadAnalysisRequest` | `MlPayloadAnalysisResponse` |
| POST | `/ml/payload-build-training-row` | Build normalized training row | Body: `MlTrainingRowBuildRequest` | `MlTrainingRowBuildResponse` |
| GET | `/ml/runtime/status` | Runtime loaded-model status | None | `MlRuntimeStatusResponse` |
| GET | `/ml/training/specs` | Feature/label/training artifact requirements | None | `MlTrainingSpecsResponse` |
| POST | `/ml/training/generate-dataset` | Generate synthetic ML dataset | Body: `MlGenerateDatasetRequest` | `MlGenerateDatasetResponse` |
| POST | `/ml/training/train` | Train selected model | Body: `MlTrainModelRequest` | `MlTrainModelResponse` |
| POST | `/ml/runtime/reload` | Reload model artifacts | Body: `MlReloadModelsRequest` | `MlReloadResponse` |
| PATCH | `/ml/runtime/default-thresholds` | Update default-risk thresholds | Body: `MlUpdateDefaultThresholdRequest` | `MlThresholdUpdateResponse` |
| POST | `/ml/score` | Risk-tier inference | Body: `RiskFeatureInput` | `MlScoreResponse` |
| POST | `/risk/recommend-deposit` | Rule-based deposit recommendation | Body: `DepositRecommendationRequest` | `DepositRecommendationResponse` |
| GET | `/ml/deposit-health` | Deposit model health | None | `MlHealthResponse` |
| GET | `/ml/default-health` | Default model health | None | `MlHealthResponse` |
| POST | `/ml/predict-default` | Predict missed next installment | Body: `DefaultPredictionInput` | `DefaultPredictionResponse` |
| POST | `/ml/recommend-deposit` | ML deposit recommendation | Body: `DepositRecommendationRequest` | `DepositRecommendationResponse` |
| POST | `/ml/orchestrate` | Multi-model run in one call | Body: `MlOrchestrationRequest` | `MlOrchestrationResponse` |
| POST | `/ml/emi/evaluate` | Evaluate ML outputs across EMI plans | Body: `MlEmiPlanEvaluationRequest` | `MlEmiEvaluationResponse` |

### 6.3 Protocol simulation APIs

| Method | Path | Use | Request payload schema | Response payload schema |
|---|---|---|---|---|
| POST | `/oracle/update-prices` | Update simulated oracle prices | Body: `OracleUpdatePricesRequest` | `ProtocolPriceUpdateResponse` |
| GET | `/oracle/prices` | Read current oracle prices | None | `ProtocolPriceReadResponse` |
| POST | `/users/set-currency` | Set user borrow currency | Body: `UserSetCurrencyRequest` | `ProtocolSetCurrencyResponse` |
| POST | `/collateral/deposit` | Deposit collateral | Body: `CollateralRequest` | `ProtocolCollateralDepositResponse` |
| POST | `/collateral/withdraw` | Withdraw collateral | Body: `CollateralRequest` | `ProtocolCollateralWithdrawResponse` |
| POST | `/borrow` | Borrow debt token | Body: `BorrowRequest` | `ProtocolBorrowResponse` |
| POST | `/repay` | Repay outstanding debt | Body: `RepayRequest` | `ProtocolRepayResponse` |
| GET | `/account/{wallet}` | Read account position | Path: `wallet` | `ProtocolAccountResponse` |
| GET | `/positions/all` | List all positions | Query: `liquidatable_only` | `ProtocolPositionsResponse` |
| POST | `/liquidate` | Liquidate unhealthy position | Body: `LiquidateRequest` | `ProtocolLiquidateResponse` |
| GET | `/archive/liquidations` | Liquidation history | Query: `page`, `page_size`, `currency` | `ProtocolArchiveResponse` |
| GET | `/stats` | Protocol aggregate stats | None | `ProtocolStatsResponse` |

### 6.4 User, Firebase, and Web3 utility APIs

| Method | Path | Use | Request payload schema | Response payload schema |
|---|---|---|---|---|
| POST | `/users` | Create user document | Body: `UserModel` | `UserModel` |
| POST | `/users/from-firebase` | Create user by `user_id` with profile enrichment | Body: `UserFromFirebaseCreateRequest` | `UserModel` |
| GET | `/users/{user_id}` | Fetch user | Path: `user_id` | `UserModel` |
| GET | `/users/{user_id}/wallets` | Fetch wallet list only | Path: `user_id` | `UserWalletDetailsResponse` |
| PUT | `/users/{user_id}` | Update user | Path: `user_id`; Body: `UserModel` | `UserModel` |
| GET | `/firebase/health` | Firestore connectivity check | None | `FirebaseHealthResponse` |
| GET | `/get-data` | Read contract values (legacy path) | None | `Web3ReadResponse` |
| GET | `/web3/health` | Web3 provider connectivity | None | `Web3HealthResponse` |
| GET | `/web3/get-data` | Read contract values (namespaced) | None | `Web3ReadResponse` |
| GET | `/web3/account/{wallet}` | Get on-chain account snapshot (balance + debt left) | Path: `wallet`; Query: `chain` | `Web3AccountSnapshotResponse` |
| GET | `/web3/tx-history/{wallet}` | Get on-chain contract event transaction history | Path: `wallet`; Query: `chain`, `from_block`, `to_block`, `limit` | `Web3TxHistoryResponse` |

### 6.5 BNPL APIs

| Method | Path | Use | Request payload schema | Response payload schema |
|---|---|---|---|---|
| GET | `/bnpl/features/status` | Implemented BNPL feature flags | None | `BnplFeatureStatusResponse` |
| GET | `/bnpl/emi/plans` | List EMI catalog plans | Query: `currency`, `include_disabled` | `BnplEmiPlansResponse` |
| GET | `/bnpl/emi/plans/{plan_id}` | Fetch one EMI plan | Path: `plan_id` | `dict` (EMI plan object) |
| GET | `/bnpl/payments/razorpay/features` | Map features using Razorpay | None | `BnplRazorpayFeatureMapResponse` |
| GET | `/bnpl/payments/razorpay/status` | Razorpay runtime status | None | `BnplRazorpayStatusResponse` |
| POST | `/bnpl/plans` | Create BNPL plan and schedule | Body: `BnplCreatePlanRequest` | `BnplPlanCreateResponse` |
| POST | `/bnpl/collateral/lock` | Lock security collateral | Body: `BnplLockDepositRequest` | `BnplCollateralMutationResponse` |
| POST | `/bnpl/collateral/topup` | Top up collateral | Body: `BnplTopUpRequest` | `BnplCollateralMutationResponse` |
| GET | `/bnpl/safety-meter/{loan_id}` | Health factor view | Path: `loan_id` | `BnplSafetyMeterResponse` |
| POST | `/bnpl/alerts/scan` | Generate early warnings | Query: `threshold_ratio` | `BnplAlertsScanResponse` |
| GET | `/bnpl/eligibility/{user_id}` | Compute eligibility | Path: `user_id` | `BnplEligibilityResponse` |
| PATCH | `/bnpl/users/autopay` | Toggle autopay | Body: `BnplAutopayRequest` | `BnplAutopayToggleResponse` |
| POST | `/bnpl/users/autopay/mandate` | Create Razorpay mandate simulation | Body: `BnplAutopayMandateRequest` | `BnplAutopayMandateResponse` |
| POST | `/bnpl/disputes/open` | Open dispute and freeze penalties | Header: `x-actor-id`; Body: `BnplDisputeRequest` | `BnplDisputeOpenResponse` |
| POST | `/bnpl/disputes/resolve` | Resolve dispute | Header: `x-actor-id`; Body: `BnplDisputeResolveRequest` | `BnplDisputeResolveResponse` |
| POST | `/bnpl/disputes/refund` | Process dispute refund | Body: `BnplDisputeRefundRequest` | `BnplDisputeRefundResponse` |
| POST | `/bnpl/payments/late-fee/preview` | Preview grace/late fee | Body: `BnplMissedSimulationRequest` | `BnplLateFeePreviewResponse` |
| POST | `/bnpl/simulations/missed-payment` | Missed-payment what-if simulation | Body: `BnplMissedSimulationRequest` | `BnplMissedSimulationResponse` |
| POST | `/bnpl/recovery/partial` | Execute partial recovery | Header: `x-admin-role`; Body: `BnplPartialRecoveryRequest` | `BnplPartialRecoveryResponse` |
| POST | `/bnpl/merchant/settlements` | Merchant upfront settlement record | Body: `BnplMerchantSettlementRequest` | `BnplMerchantSettlementResponse` |
| GET | `/bnpl/merchant/{merchant_id}/dashboard` | Merchant dashboard | Path: `merchant_id` | `BnplMerchantDashboardResponse` |
| GET | `/bnpl/merchant/risk-view/{loan_id}` | Merchant collateral proof view | Path: `loan_id` | `BnplMerchantRiskViewResponse` |
| POST | `/bnpl/risk/score/{loan_id}` | Compute rule-based risk score | Path: `loan_id` | `BnplRiskScoreResponse` |
| GET | `/bnpl/risk/recommend-deposit/{loan_id}` | Deposit recommendation from loan context | Path: `loan_id`; Query: `use_ml` | `DepositRecommendationResponse` |
| POST | `/bnpl/risk/default-nudge` | Predict default and create nudge | Body: `BnplMissedSimulationRequest` | `BnplDefaultNudgeResponse` |
| GET | `/bnpl/explainability/{loan_id}` | Decision explainability panel | Path: `loan_id` | `BnplExplainabilityResponse` |
| GET | `/bnpl/proof/{loan_id}` | Public proof payload | Path: `loan_id` | `BnplProofResponse` |
| GET | `/bnpl/oracle/guard` | Oracle freshness guard | Query: `max_age_sec` | `BnplOracleGuardResponse` |
| GET | `/bnpl/audit/events` | Audit event logs | Query: `limit` | `BnplAuditEventsResponse` |
| PATCH | `/bnpl/admin/pause` | Emergency pause control | Headers: `x-admin-role`, `x-actor-id`; Body: `BnplAdminPauseRequest` | `BnplAdminPauseResponse` |

### 6.6 BNPL Enterprise Extension APIs (Epics 1-12)

| Method | Path | Use | Request payload schema | Response payload schema |
|---|---|---|---|---|
| POST | `/bnpl/compliance/kyc` | Update KYC lifecycle | Headers: `x-admin-role`, `x-actor-id`; Body: `KycStatusUpdateRequest` | `{"user_id","kyc_status","kyc_level",...}` |
| GET | `/bnpl/compliance/kyc/{user_id}` | Read KYC state | Path: `user_id` | `{"user_id","kyc_status",...}` |
| POST | `/bnpl/compliance/aml/screen` | Run AML/sanctions screening | Headers: `x-admin-role`, `x-actor-id`; Body: `AmlScreeningRequest` | `{"user_id","provider","status","risk_flags",...}` |
| GET | `/bnpl/compliance/aml/{user_id}` | Read AML screening status | Path: `user_id` | `{"user_id","aml_status",...}` |
| POST | `/bnpl/wallets/verify/challenge` | Create sign-message challenge | Body: `WalletVerificationChallengeRequest` | `{"message","nonce","expires_at",...}` |
| POST | `/bnpl/wallets/verify/confirm` | Verify signed wallet challenge | Body: `WalletVerificationConfirmRequest` | `{"verified", "verified_wallets", ...}` |
| GET | `/bnpl/wallets/verify/{user_id}` | Get verified wallets | Path: `user_id` | `{"verified_wallets",...}` |
| GET | `/bnpl/collateral/policies` | List collateral asset policy map | None | `{"total","policies"}` |
| PUT | `/bnpl/collateral/policies/{asset_symbol}` | Update per-asset policy | Headers: `x-admin-role`, `x-actor-id`; Body: `CollateralPolicyUpdateRequest` | `policy object` |
| GET | `/bnpl/disputes/pause-rules` | Get dispute pause rules | None | `category->rule map` |
| PUT | `/bnpl/disputes/pause-rules/{category}` | Update pause rules by dispute category | Headers: `x-admin-role`, `x-actor-id`; Body: `DisputePauseRuleRequest` | `{"category","rule"}` |
| POST | `/bnpl/disputes/{dispute_id}/evidence` | Attach dispute evidence metadata | Header: `x-actor-id`; Body: `DisputeEvidenceRequest` | `{"dispute_id","evidence"}` |
| GET | `/bnpl/disputes/loan/{loan_id}` | List disputes for loan | Path: `loan_id` | `{"loan_id","total","disputes"}` |
| POST | `/bnpl/loans/{loan_id}/state` | Enforced loan state transition | Headers: `x-admin-role`, `x-actor-id`; Body: `LoanStateTransitionRequest` | `{"from_status","to_status"}` |
| POST | `/bnpl/loans/{loan_id}/close` | Close loan with reconciliation | Headers: `x-admin-role`, `x-actor-id`; Body: `LoanCloseRequest` | `{"status":"CLOSED","release":...}` |
| POST | `/bnpl/loans/{loan_id}/collateral/release` | Release unlocked collateral | Header: `x-actor-id` | `{"released_total_minor","releases":[...]}` |
| POST | `/bnpl/loans/{loan_id}/cancel` | Cancel pre-settlement order | Header: `x-actor-id`; Body: `LoanCancelRequest` | `{"order", "release"}` |
| POST | `/bnpl/loans/{loan_id}/refund-adjust` | Apply full/partial refund adjustment | Header: `x-actor-id`; Body: `LoanRefundAdjustmentRequest` | `{"loan","refund_applied_minor"}` |
| POST | `/bnpl/payments/installment` | Pay scheduled installment | Headers: `x-actor-id`, `x-idempotency-key`; Body: `InstallmentPaymentRequest` | `{"payment_attempt","loan","installment"}` |
| POST | `/bnpl/payments/pay-now` | Manual pay-now flow | Headers: `x-actor-id`, `x-idempotency-key`; Body: `PayNowRequest` | `{"paid_minor","unapplied_minor","loan"}` |
| POST | `/bnpl/payments/retry` | Retry failed payment | Header: `x-actor-id`; Body: `PaymentRetryRequest` | `{"retry_count","result"}` |
| POST | `/bnpl/payments/webhooks/razorpay` | Reconcile Razorpay webhook event | Header: `x-razorpay-signature`; Body: `RazorpayWebhookRequest` | `{"processed","event_id","order_id"}` |
| POST | `/bnpl/payments/late-fee/apply` | Apply late fee rules | Header: `x-actor-id`; Body: `BnplMissedSimulationRequest` | `{"late_fee_applied_minor",...}` |
| POST | `/bnpl/payments/late-fee/waive` | Waive/reverse late fee | Headers: `x-admin-role`, `x-actor-id`; Body: `LateFeeWaiveRequest` | `{"loan","installment","ledger_entry"}` |
| POST | `/bnpl/reminders/schedule` | Schedule due/grace reminders | Header: `x-actor-id`; Body: `ReminderScheduleRequest` | `{"scheduled_count","reminders"}` |
| POST | `/bnpl/reminders/run-due` | Execute due reminder dispatch | Header: `x-actor-id` | `{"processed","deliveries"}` |
| POST | `/bnpl/notifications/send` | Send notification via channel abstraction | Header: `x-actor-id`; Body: `NotificationSendRequest` | `notification record` |
| GET | `/bnpl/oracle/resolve` | Resolve oracle with fallback + stale rules | Query: `max_age_sec`, `block_on_stale` | `{"healthy","selected","prices",...}` |
| POST | `/bnpl/risk/monitor` | Portfolio risk scan worker API | Query: `threshold_ratio` | `{"scanned_loans","flagged_loans","flags"}` |
| POST | `/bnpl/recovery/full` | Full liquidation / bad debt flow | Header: `x-admin-role`; Body: `FullLiquidationRequest` | `{"loan","liquidation_log","residual_bad_debt_minor"}` |
| POST | `/bnpl/fraud/check` | Fraud/abuse heuristic checks | Body: `FraudCheckRequest` | `{"flags","status",...}` |
| GET | `/bnpl/ops/dashboard` | Internal ops dashboard | Header: `x-admin-role` | `counts + kpis + recent failures` |
| GET | `/bnpl/ledger` | Ledger records for accounting reconstruction | Query: `loan_id`, `user_id`, `limit` | `{"total","entries"}` |
| GET | `/bnpl/metrics/kpi` | KPI metrics endpoint | None | `approval/default/refund/dispute/liquidation metrics` |
| POST | `/bnpl/jobs/enqueue` | Enqueue async scheduler job | Header: `x-actor-id`; Body: `JobEnqueueRequest` | `job payload` |
| POST | `/bnpl/jobs/run-due` | Execute due jobs | Header: `x-actor-id` | `{"processed","jobs"}` |
| POST | `/bnpl/merchant/onboard` | Merchant onboarding + API key | Headers: `x-admin-role`, `x-actor-id`; Body: `MerchantOnboardRequest` | `merchant record` |
| POST | `/bnpl/merchant/auth/validate` | Validate merchant API key | Body: `MerchantAuthRequest` | `{"valid","active"}` |
| PATCH | `/bnpl/merchant/orders/{order_id}/status` | Merchant order/fulfillment sync | Headers: `x-admin-role`, `x-actor-id`; Body: `MerchantOrderStatusRequest` | `updated order` |
| GET | `/bnpl/merchant/{merchant_id}/settlements` | Settlement lifecycle tracking | Path: `merchant_id` | `{"lifecycle","orders"}` |
| GET | `/bnpl/merchant/{merchant_id}/risk-score` | Merchant risk scoring | Path: `merchant_id` | `{"merchant_risk_score","signals"}` |
| POST | `/bnpl/admin/manual/waive-penalty` | Manual override penalty waiver | Headers: `x-admin-role`, `x-actor-id`; Body: `LateFeeWaiveRequest` | `waive result` |
| POST | `/bnpl/admin/manual/force-close/{loan_id}` | Manual force-close | Headers: `x-admin-role`, `x-actor-id`; Body: `LoanCancelRequest` | `force close result` |
| POST | `/bnpl/admin/manual/retry-settlement/{order_id}` | Manual settlement retry | Headers: `x-admin-role`, `x-actor-id` | `updated order` |
| GET | `/bnpl/users/{user_id}/loans` | User active/closed/defaulted loans list | Path: `user_id`; Query: `include_closed` | `loan summaries` |
| GET | `/bnpl/loans/{loan_id}/detail` | Full loan detail payload | Path: `loan_id` | `loan + collateral + health + dispute + fee summary` |
| GET | `/bnpl/loans/{loan_id}/installments` | Installment schedule/history | Path: `loan_id` | `{"total","installments"}` |
| GET | `/bnpl/loans/{loan_id}/payments` | Payment/retry history timeline | Path: `loan_id`; Query: `limit` | `{"total","payments"}` |

### 6.7 Risk v2 API (`backend/api/risk_routes.py`)

| Method | Path | Use | Request payload schema | Response payload schema |
|---|---|---|---|---|
| POST | `/api/risk/predict` | Predict liquidation probability with model/fallback | Body: `RiskPredictRequest` | `RiskPredictResponse` |

---

## 8) Important integration notes

- Firestore-dependent APIs (`/users*`, `/firebase/health`, many BNPL flows in Firestore mode) return `503` when Firebase client is unavailable.
- Web3-dependent APIs (`/get-data`, `/web3/*`, `/wallet/balance` chain RPC) return `503` if provider/config is unavailable.
- ML APIs return `503` when model loading is disabled/unavailable.
- BNPL admin routes require headers:
  - `x-admin-role: ADMIN|PAUSER` for `/bnpl/admin/pause`
  - `x-admin-role: ADMIN|LIQUIDATOR` for `/bnpl/recovery/partial`
  - `x-admin-role: ADMIN|SUPPORT|REVIEWER` for compliance, manual-review, and state-transition endpoints
- Write-heavy BNPL routes support idempotency through `x-idempotency-key` (currently enforced on plan create, collateral lock/topup, installment pay-now/payment, and settlement).
- Sensitive payment routes are rate-limited per caller/IP and return `429` on bursts.

## 9) Testing tip

Use `GET /settings` first to verify which integrations are enabled before calling dependency-heavy endpoints.
