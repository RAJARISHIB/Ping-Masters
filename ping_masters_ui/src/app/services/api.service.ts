import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

// ── Request models ─────────────────────────────────────────────────────────────

export interface MarketChartRequest {
  symbol: string;
  timeframe: string;
  vs_currency: string;
}

export interface RiskPredictRequest {
  wallet_address: string;
  collateral_bnb?: number;
  debt_fiat?: number;
  current_price?: number;
  volatility?: number;
}

export interface RiskFeatureInput {
  safety_ratio: number;
  missed_payment_count: number;
  on_time_ratio: number;
  avg_delay_hours: number;
  topup_count_last_30d: number;
  plan_amount: number;
  tenure_days: number;
  installment_amount: number;
}

export interface BnplCreatePlanRequest {
  user_id: string;
  merchant_id: string;
  principal_minor: number;
  currency: string;
  installment_count: number;
  tenure_days: number;
  ltv_bps: number;
  collateral_asset?: string;
  oracle_price_minor?: number;
}

export interface BnplLockDepositRequest {
  loan_id: string;
  user_id: string;
  asset_symbol: string;
  deposited_units: number;
  collateral_value_minor: number;
  oracle_price_minor: number;
  vault_address?: string;
  chain_id?: string;
  deposit_tx_hash?: string;
}

export interface BnplAutopayMandateRequest {
  user_id: string;
  loan_id: string;
  amount_minor: number;
  currency: string;
  customer_name?: string;
  customer_email?: string;
  customer_contact?: string;
}

// ── Response models ────────────────────────────────────────────────────────────

export interface MarketChartResponse {
  coin_id: string;
  symbol_input: string;
  timeframe: string;
  vs_currency: string;
  points: number;
  prices: [number, number][];    // [timestamp_ms, price]
  market_caps?: [number, number][];
  total_volumes?: [number, number][];
}

export interface RiskPredictResponse {
  wallet_address: string;
  prediction: {
    liquidation_probability: number;
    risk_tier: string;
    model_version: string;
  };
  current_position: Record<string, any>;
  risk_factors: Record<string, any>;
  timestamp: string;
}

export interface MlScoreResponse {
  risk_tier: string;
  probabilities: Record<string, number>;
  top_reasons: string[];
  model_name: string;
  model_version: string;
}

export interface BnplPlanCreateResponse {
  loan: Record<string, any>;
  installments: any[];
  emi_plan: Record<string, any>;
}

export interface BnplCollateralMutationResponse {
  collateral: Record<string, any>;
  safety_meter: Record<string, any>;
}

export interface BnplAutopayMandateResponse {
  loan_id: string;
  user_id: string;
  amount_minor: number;
  provider: string;
  payment_link: string;
}

export interface SettingsSnapshotResponse {
  [key: string]: any;
}

export interface WalletValidationResponse {
  wallet: string;
  is_valid: boolean;
  checksum_address?: string;
}

export interface UserWalletDetailsResponse {
  user_id: string;
  wallet_address: Array<{ name: string; wallet_id: string }>;
  wallet_count: number;
}

export interface UserProfileResponse {
  user_id: string;
  email?: string;
  phone?: string;
  full_name?: string;
  currency_code?: string;
  currency_symbol?: string;
  [key: string]: any;
}

export interface CurrencyConvertResponse {
  amount: number;
  from_currency: string;
  to_currency: string;
  converted_amount: number;
  rate: number;
  provider?: string;
  raw?: Record<string, any>;
}

export interface WalletBalanceResponse {
  wallet: string;
  chain: string;
  balance_wei: string;
  balance_bnb: number;
}

export interface BnplEligibilityResponse {
  user_id: string;
  total_collateral_minor: number;
  max_credit_minor: number;
  outstanding_minor: number;
  available_credit_minor: number;
  ltv_bps: number;
}

export interface BnplSafetyMeterResponse {
  loan_id: string;
  collateral_value_minor: number;
  outstanding_minor: number;
  health_factor: number;
  safety_color: string;
  [key: string]: any;
}

export interface BnplExplainabilityResponse {
  loan_id: string;
  reasons: string[];
  risk_score?: Record<string, any>;
  deposit_recommendation?: Record<string, any>;
  safety_meter?: Record<string, any>;
}

export interface BnplProofResponse {
  loan_id?: string;
  [key: string]: any;
}

export interface BnplAuditEventsResponse {
  total: number;
  events: Array<Record<string, any>>;
}

export interface BnplEmiPlanItem {
  plan_id: string;
  plan_name?: string;
  installment_count: number;
  tenure_days?: number;
  enabled?: boolean;
  currency_scope?: string[];
  [key: string]: any;
}

export interface BnplEmiPlansResponse {
  total: number;
  currency?: string | null;
  plans: BnplEmiPlanItem[];
}

export interface DepositRecommendationResponse {
  mode: string;
  risk_tier: string;
  required_inr: number;
  required_token: number;
  current_locked_token: number;
  current_locked_inr: number;
  topup_token: number;
  [key: string]: any;
}

export interface BnplRazorpayStatusResponse {
  enabled: boolean;
  configured: boolean;
  available: boolean;
}

// ── Razorpay types ─────────────────────────────────────────────────────────────

export interface RazorpayOptions {
  key: string;
  amount: number;          // in paise
  currency: string;
  name: string;
  description: string;
  order_id?: string;
  handler: (response: RazorpaySuccessResponse) => void;
  prefill?: { name?: string; email?: string; contact?: string };
  theme?: { color?: string };
  modal?: { ondismiss?: () => void };
}

export interface RazorpaySuccessResponse {
  razorpay_payment_id: string;
  razorpay_order_id?: string;
  razorpay_signature?: string;
}

// ── ApiService ─────────────────────────────────────────────────────────────────

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly base = environment.apiUrl;

  constructor(private http: HttpClient) {}

  // ── Settings ──────────────────────────────────────────────────────────────

  getSettings(): Observable<SettingsSnapshotResponse> {
    return this.http.get<SettingsSnapshotResponse>(`${this.base}/settings`);
  }

  // ── Wallet / User ───────────────────────────────────────────────────────

  validateWallet(wallet: string): Observable<WalletValidationResponse> {
    return this.http.get<WalletValidationResponse>(`${this.base}/wallet/validate`, {
      params: { wallet }
    });
  }

  getWalletBalance(wallet: string, chain: 'bsc' | 'opbnb' = 'bsc'): Observable<WalletBalanceResponse> {
    return this.http.get<WalletBalanceResponse>(`${this.base}/wallet/balance`, {
      params: { wallet, chain }
    });
  }

  getUserWallets(userId: string): Observable<UserWalletDetailsResponse> {
    return this.http.get<UserWalletDetailsResponse>(`${this.base}/users/${userId}/wallets`);
  }

  getUser(userId: string): Observable<UserProfileResponse> {
    return this.http.get<UserProfileResponse>(`${this.base}/users/${userId}`);
  }

  // ── Market ────────────────────────────────────────────────────────────────

  getBnbChart(timeframe = '1D', vsCurrency = 'usd'): Observable<MarketChartResponse> {
    return this.http.post<MarketChartResponse>(`${this.base}/market/chart`, {
      symbol: 'bnb',
      timeframe,
      vs_currency: vsCurrency,
    } as MarketChartRequest);
  }

  convertCurrency(amount: number, fromCurrency: string, toCurrency: string): Observable<CurrencyConvertResponse> {
    return this.http.get<CurrencyConvertResponse>(`${this.base}/currency/convert`, {
      params: {
        amount,
        from_currency: fromCurrency,
        to_currency: toCurrency,
      },
    });
  }

  // ── Risk / ML ─────────────────────────────────────────────────────────────

  predictRisk(req: RiskPredictRequest): Observable<RiskPredictResponse> {
    return this.http.post<RiskPredictResponse>(`${this.base}/api/risk/predict`, req);
  }

  mlScore(req: RiskFeatureInput): Observable<MlScoreResponse> {
    return this.http.post<MlScoreResponse>(`${this.base}/ml/score`, req);
  }

  // ── BNPL ──────────────────────────────────────────────────────────────────

  createBnplPlan(req: BnplCreatePlanRequest): Observable<BnplPlanCreateResponse> {
    return this.http.post<BnplPlanCreateResponse>(`${this.base}/bnpl/plans`, req);
  }

  lockCollateral(req: BnplLockDepositRequest): Observable<BnplCollateralMutationResponse> {
    return this.http.post<BnplCollateralMutationResponse>(`${this.base}/bnpl/collateral/lock`, req);
  }

  createAutopayMandate(req: BnplAutopayMandateRequest): Observable<BnplAutopayMandateResponse> {
    return this.http.post<BnplAutopayMandateResponse>(`${this.base}/bnpl/users/autopay/mandate`, req);
  }

  getBnplEligibility(userId: string): Observable<BnplEligibilityResponse> {
    return this.http.get<BnplEligibilityResponse>(`${this.base}/bnpl/eligibility/${userId}`);
  }

  getBnplSafetyMeter(loanId: string): Observable<BnplSafetyMeterResponse> {
    return this.http.get<BnplSafetyMeterResponse>(`${this.base}/bnpl/safety-meter/${loanId}`);
  }

  getBnplExplainability(loanId: string): Observable<BnplExplainabilityResponse> {
    return this.http.get<BnplExplainabilityResponse>(`${this.base}/bnpl/explainability/${loanId}`);
  }

  getBnplProof(loanId: string): Observable<BnplProofResponse> {
    return this.http.get<BnplProofResponse>(`${this.base}/bnpl/proof/${loanId}`);
  }

  getBnplDepositRecommendation(loanId: string, useMl = true): Observable<DepositRecommendationResponse> {
    return this.http.get<DepositRecommendationResponse>(`${this.base}/bnpl/risk/recommend-deposit/${loanId}`, {
      params: { use_ml: useMl }
    });
  }

  getBnplAuditEvents(limit = 20): Observable<BnplAuditEventsResponse> {
    return this.http.get<BnplAuditEventsResponse>(`${this.base}/bnpl/audit/events`, {
      params: { limit }
    });
  }

  /** List EMI plans (e.g. for Borrow page installment options). */
  getBnplEmiPlans(currency?: string, includeDisabled = false): Observable<BnplEmiPlansResponse> {
    const params: { currency?: string; include_disabled?: boolean } = {};
    if (currency) params.currency = currency;
    if (includeDisabled) params.include_disabled = true;
    return this.http.get<BnplEmiPlansResponse>(`${this.base}/bnpl/emi/plans`, { params });
  }

  getRazorpayStatus(): Observable<BnplRazorpayStatusResponse> {
    return this.http.get<BnplRazorpayStatusResponse>(`${this.base}/bnpl/payments/razorpay/status`);
  }

  // ── Razorpay checkout helper ──────────────────────────────────────────────

  /**
   * Waits for the Razorpay script to be available on window (with timeout).
   * Call before openRazorpayCheckout to avoid "Razorpay SDK not loaded" when script loads async.
   */
  waitForRazorpayScript(timeoutMs = 8000): Promise<void> {
    return new Promise((resolve, reject) => {
      if ((window as any)['Razorpay']) {
        resolve();
        return;
      }
      const deadline = Date.now() + timeoutMs;
      const t = setInterval(() => {
        if ((window as any)['Razorpay']) {
          clearInterval(t);
          resolve();
          return;
        }
        if (Date.now() >= deadline) {
          clearInterval(t);
          reject(new Error('Razorpay SDK did not load in time. Please refresh and try again.'));
        }
      }, 150);
    });
  }

  /**
   * Opens the Razorpay checkout modal.
   * Waits for the SDK script to load, then opens the modal.
   * Resolves with success response or rejects when dismissed or on error.
   */
  async openRazorpayCheckout(
    amountMinor: number,
    currency: string,
    description: string,
    prefill?: { name?: string; email?: string; contact?: string }
  ): Promise<RazorpaySuccessResponse> {
    await this.waitForRazorpayScript();
    const Razorpay = (window as any)['Razorpay'];
    if (!Razorpay) {
      throw new Error('Razorpay SDK not loaded');
    }
    return new Promise((resolve, reject) => {
      const options: RazorpayOptions = {
        key: environment.razorpayKey,
        amount: amountMinor,
        currency: String(currency || "USD").toUpperCase(),
        name: 'Ping Masters',
        description,
        handler: (response) => resolve(response),
        prefill: prefill ?? {},
        theme: { color: '#f59e0b' },
        modal: {
          ondismiss: () => reject(new Error('Payment cancelled by user')),
        },
      };
      const rzp = new Razorpay(options);
      rzp.open();
    });
  }

  /** Convert major currency units to minor units (x100), rounded to integer. */
  static toPaise(amountMajor: number): number {
    return Math.round(amountMajor * 100);
  }
}
