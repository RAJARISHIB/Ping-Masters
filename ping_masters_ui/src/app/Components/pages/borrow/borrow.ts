import { Component, OnDestroy, OnInit } from "@angular/core";
import { Router } from "@angular/router";
import { FormsModule } from "@angular/forms";
import { firstValueFrom, forkJoin, of } from "rxjs";
import { catchError } from "rxjs/operators";
import { SharedModule } from "../../../app.module";
import {
    ApiService,
    DefaultPredictionRequest,
    DefaultPredictionResponse,
    DepositRecommendationRequest,
    DepositRecommendationResponse,
    RiskFeatureInput,
} from "../../../services/api.service";
import { CurrencySymbolService } from "../../../services/currency-symbol.service";

type EthereumProvider = {
    request: (args: { method: string; params?: unknown[] }) => Promise<unknown>;
};

interface BorrowForm {
    loanName: string;
    amount: number | null;
    installments: number;
    repaymentDate: string;
    notifications: string[];
}

@Component({
    selector: "app-borrow",
    templateUrl: "./borrow.html",
    styleUrls: ["./borrow.scss"],
    standalone: true,
    imports: [SharedModule, FormsModule],
})
export class Borrow implements OnInit, OnDestroy {
    readonly chartW = 600;
    readonly chartH = 140;
    readonly POINTS = 60;
    readonly collateralCoverageRatio = 1.5;
    readonly liquidationCoverageRatio = 1.2;

    bnbPrice = 0; // display currency
    bnbHigh = 0; // display currency
    bnbLow = 0; // display currency
    bnbChange = 0;
    priceHistory: number[] = []; // display currency
    svgPath = "";
    chartMin = 0;
    chartMax = 0;

    bnbPriceUsd = 0;
    priceHistoryUsd: number[] = [];

    creditScore = 742;
    riskTier = "MEDIUM";
    creditScoreLoading = false;
    mlRiskLoading = false;
    depositRecommendationLoading = false;
    defaultPredictionLoading = false;
    mlInsightsError = "";
    mlModelRiskTier = "MEDIUM";
    mlRiskProbabilities: Record<string, number> = {};
    mlRiskReasons: string[] = [];
    depositPolicyRecommendation: DepositRecommendationResponse | null = null;
    depositMlRecommendation: DepositRecommendationResponse | null = null;
    depositPolicyRequiredUser = 0;
    depositMlRequiredUser = 0;
    defaultPrediction: DefaultPredictionResponse | null = null;

    minBorrow = 500;
    maxBorrow = 50000;

    connectedWallet = "";
    walletValidationError = "";
    walletValidating = false;
    isConnectingWallet = false;
    eligibilityLoading = false;
    eligibilityAvailableCredit = 0;
    eligibilityLtvBps = 0;

    userId = "";
    userCurrencyCode = "USD";
    userCurrencySymbol = "";
    userToUsdRate = 1.0;
    usdToUserRate = 1.0;
    userOnTimePaymentCount = 0;
    userLatePaymentCount = 0;
    userTopupCount = 0;
    userWalletAgeDays = 180;

    form: BorrowForm = {
        loanName: "",
        amount: null,
        installments: 6,
        repaymentDate: "",
        notifications: ["email"],
    };

    installmentOptions: number[] = [3, 6, 12, 24];
    notificationChannels = [
        { key: "email", icon: "fa-solid fa-envelope", label: "Email" },
        { key: "whatsapp", icon: "fa-brands fa-whatsapp", label: "WhatsApp" },
        { key: "phone", icon: "fa-solid fa-phone", label: "Phone" },
        { key: "telegram", icon: "fa-brands fa-telegram", label: "Telegram" },
    ];

    private riskRefreshTimer: ReturnType<typeof setTimeout> | null = null;
    private mlRequestVersion = 0;

    get emiAmount(): number {
        if (!this.form.amount || !this.form.installments) return 0;
        const interest = 0.12 / 12;
        const n = this.form.installments;
        const p = this.form.amount;
        return Math.ceil((p * interest * Math.pow(1 + interest, n)) / (Math.pow(1 + interest, n) - 1));
    }

    get collateralRequired(): number {
        if (!this.form.amount || this.form.amount <= 0 || this.bnbPriceUsd <= 0) return 0;
        const debtUsd = this.convertUserToUsd(this.form.amount);
        if (debtUsd <= 0) return 0;
        return parseFloat(((debtUsd * this.collateralCoverageRatio) / this.bnbPriceUsd).toFixed(4));
    }

    get liquidationPrice(): number {
        const collateralBnb = this.collateralRequired;
        if (!this.form.amount || collateralBnb <= 0) return 0;
        const debtUsd = this.convertUserToUsd(this.form.amount);
        const liquidationPriceUsd = (debtUsd * this.liquidationCoverageRatio) / collateralBnb;
        return parseFloat(this.convertUsdToUser(liquidationPriceUsd).toFixed(2));
    }

    get isValid(): boolean {
        return !!(
            this.connectedWallet &&
            !this.walletValidationError &&
            this.form.loanName.trim() &&
            this.form.amount &&
            this.form.amount >= this.minBorrow &&
            this.form.amount <= this.maxBorrow &&
            this.form.repaymentDate &&
            this.form.notifications.length > 0
        );
    }

    constructor(
        private router: Router,
        private api: ApiService,
        private currencySymbols: CurrencySymbolService,
    ) {}

    ngOnInit(): void {
        const saved = sessionStorage.getItem("borrow_form");
        if (saved) {
            try {
                this.form = { ...this.form, ...JSON.parse(saved) };
            } catch {
                this.form = { ...this.form };
            }
        }

        if (!this.form.repaymentDate) {
            this.setRepaymentDate();
        }

        this.userId = sessionStorage.getItem("user_id") || "user_001";
        this.userCurrencySymbol = this.currencySymbols.resolveSymbol(this.userCurrencyCode);
        this.loadUserCurrencyContext();
        this.loadEligibility();
        this.loadBnbChart();
        this.loadEmiPlans();

        const savedWallet = sessionStorage.getItem("connected_wallet");
        if (savedWallet) {
            this.connectedWallet = savedWallet;
            this.validateConnectedWallet();
            this.loadRiskScore();
        }
    }

    private loadUserCurrencyContext(): void {
        if (!this.userId) return;

        this.api.getUser(this.userId).pipe(catchError(() => of(null))).subscribe((user) => {
            const currencyCode = String(user?.currency_code || this.userCurrencyCode || "USD").toUpperCase();
            this.userCurrencyCode = currencyCode;
            this.userCurrencySymbol = this.currencySymbols.resolveSymbol(currencyCode);
            this.userOnTimePaymentCount = Number(user?.["on_time_payment_count"] || 0);
            this.userLatePaymentCount = Number(user?.["late_payment_count"] || 0);
            this.userTopupCount = Number(user?.["top_up_count"] || 0);

            const createdAtRaw = String(user?.["created_at"] || "").trim();
            if (createdAtRaw) {
                const createdAt = new Date(createdAtRaw);
                if (!Number.isNaN(createdAt.getTime())) {
                    const ageMs = Date.now() - createdAt.getTime();
                    this.userWalletAgeDays = Math.max(1, Math.floor(ageMs / (24 * 60 * 60 * 1000)));
                }
            }
            this.bootstrapFxRates();
            this.loadEligibility();
            this.loadEmiPlans();
        });
    }

    private bootstrapFxRates(): void {
        if (this.userCurrencyCode === "USD") {
            this.userToUsdRate = 1.0;
            this.usdToUserRate = 1.0;
            this.applyDisplaySeriesFromUsd();
            this.loadRiskScore();
            return;
        }

        forkJoin({
            toUsd: this.api
                .convertCurrency(1, this.userCurrencyCode, "USD")
                .pipe(catchError(() => of(null))),
            fromUsd: this.api
                .convertCurrency(1, "USD", this.userCurrencyCode)
                .pipe(catchError(() => of(null))),
        }).subscribe(({ toUsd, fromUsd }) => {
            const toUsdRate = Number(toUsd?.rate || toUsd?.converted_amount || 0);
            const fromUsdRate = Number(fromUsd?.rate || fromUsd?.converted_amount || 0);

            if (toUsdRate > 0) {
                this.userToUsdRate = toUsdRate;
            } else {
                this.userToUsdRate = 1.0;
            }

            if (fromUsdRate > 0) {
                this.usdToUserRate = fromUsdRate;
            } else if (this.userToUsdRate > 0) {
                this.usdToUserRate = 1.0 / this.userToUsdRate;
            } else {
                this.usdToUserRate = 1.0;
            }

            this.applyDisplaySeriesFromUsd();
            this.loadRiskScore();
        });
    }

    private convertUserToUsd(value: number): number {
        if (!Number.isFinite(value) || value <= 0) return 0;
        if (this.userCurrencyCode === "USD") return value;
        if (!Number.isFinite(this.userToUsdRate) || this.userToUsdRate <= 0) return value;
        return value * this.userToUsdRate;
    }

    private convertUsdToUser(value: number): number {
        if (!Number.isFinite(value) || value <= 0) return 0;
        if (this.userCurrencyCode === "USD") return value;
        if (!Number.isFinite(this.usdToUserRate) || this.usdToUserRate <= 0) return value;
        return value * this.usdToUserRate;
    }

    private loadEmiPlans(): void {
        this.api.getBnplEmiPlans(this.userCurrencyCode, false).subscribe({
            next: (res) => {
                if (!res.plans || res.plans.length === 0) return;
                const counts = res.plans
                    .map((plan) => Number(plan.installment_count))
                    .filter((months) => Number.isInteger(months) && months > 0);
                const unique = [...new Set(counts)].sort((a, b) => a - b);
                if (!unique.length) return;
                this.installmentOptions = unique;
                if (!this.installmentOptions.includes(this.form.installments)) {
                    this.form.installments = this.installmentOptions[0];
                    this.setRepaymentDate();
                }
            },
            error: () => {
                this.installmentOptions = [3, 6, 12, 24];
            },
        });
    }

    private loadEligibility(): void {
        this.eligibilityLoading = true;
        this.api.getBnplEligibility(this.userId).subscribe({
            next: (res) => {
                this.eligibilityLoading = false;
                this.eligibilityAvailableCredit = Number(res.available_credit_minor || 0) / 100;
                this.eligibilityLtvBps = Number(res.ltv_bps || 0);
                if (this.eligibilityAvailableCredit > 0) {
                    this.maxBorrow = Math.floor(this.eligibilityAvailableCredit);
                }
            },
            error: () => {
                this.eligibilityLoading = false;
            },
        });
    }

    private loadBnbChart(): void {
        this.api.getBnbChart("1D", "usd").subscribe({
            next: (res) => {
                if (!res.prices || !res.prices.length) {
                    this.priceHistory = [];
                    this.priceHistoryUsd = [];
                    this.svgPath = "";
                    return;
                }

                const pricesUsd = res.prices
                    .map((point) => Number(point[1]))
                    .filter((price) => Number.isFinite(price) && price > 0);
                if (!pricesUsd.length) return;

                this.priceHistoryUsd = pricesUsd.slice(-this.POINTS);
                while (this.priceHistoryUsd.length < this.POINTS) {
                    this.priceHistoryUsd.unshift(this.priceHistoryUsd[0]);
                }
                this.bnbPriceUsd = this.priceHistoryUsd[this.priceHistoryUsd.length - 1];

                this.applyDisplaySeriesFromUsd();
                this.loadRiskScore();
            },
            error: () => {
                this.priceHistory = [];
                this.priceHistoryUsd = [];
                this.svgPath = "";
            },
        });
    }

    private applyDisplaySeriesFromUsd(): void {
        if (!this.priceHistoryUsd.length) {
            this.priceHistory = [];
            this.svgPath = "";
            return;
        }

        this.priceHistory = this.priceHistoryUsd.map((priceUsd) => this.convertUsdToUser(priceUsd));
        this.bnbPrice = this.priceHistory[this.priceHistory.length - 1];
        this.bnbHigh = Math.max(...this.priceHistory);
        this.bnbLow = Math.min(...this.priceHistory);
        this.chartMin = Math.max(1, this.bnbLow * 0.98);
        this.chartMax = this.bnbHigh * 1.02;

        const first = this.priceHistory[0] || this.bnbPrice;
        this.bnbChange = first > 0 ? parseFloat((((this.bnbPrice - first) / first) * 100).toFixed(2)) : 0;
        this.buildPath();
    }

    loadRiskScore(): void {
        if (!this.connectedWallet || !this.form.amount || !this.bnbPriceUsd) {
            this.mlInsightsError = "";
            this.mlModelRiskTier = this.riskTier;
            this.mlRiskProbabilities = {};
            this.mlRiskReasons = [];
            this.depositPolicyRecommendation = null;
            this.depositMlRecommendation = null;
            this.defaultPrediction = null;
            this.mlRiskLoading = false;
            this.depositRecommendationLoading = false;
            this.defaultPredictionLoading = false;
            return;
        }

        const debtUsd = this.convertUserToUsd(this.form.amount);
        if (debtUsd <= 0) return;

        this.creditScoreLoading = true;
        this.api
            .predictRisk({
                wallet_address: this.connectedWallet,
                collateral_bnb: this.collateralRequired || 1.0,
                debt_fiat: debtUsd,
                current_price: this.bnbPriceUsd,
            })
            .subscribe({
                next: (res) => {
                    this.creditScoreLoading = false;
                    this.riskTier = res.prediction?.risk_tier ?? "MEDIUM";
                    const probability = Number(res.prediction?.liquidation_probability ?? 0.3);
                    this.creditScore = Math.round(900 - probability * 600);
                    void this.refreshMlInsights();
                },
                error: () => {
                    this.creditScoreLoading = false;
                    void this.refreshMlInsights();
                },
            });
    }

    onAmountChanged(): void {
        this.scheduleRiskRefresh();
    }

    private scheduleRiskRefresh(delayMs: number = 320): void {
        if (this.riskRefreshTimer) {
            clearTimeout(this.riskRefreshTimer);
        }
        this.riskRefreshTimer = setTimeout(() => {
            this.loadRiskScore();
        }, delayMs);
    }

    get isMlInsightsLoading(): boolean {
        return this.mlRiskLoading || this.depositRecommendationLoading || this.defaultPredictionLoading;
    }

    private getDerivedOnTimeRatio(): number {
        const onTime = Math.max(0, this.userOnTimePaymentCount);
        const late = Math.max(0, this.userLatePaymentCount);
        const total = onTime + late;
        if (total <= 0) return 0.85;
        return Math.max(0, Math.min(1, onTime / total));
    }

    private normalizeMlReasons(rawReasons: Array<Record<string, any> | string> = []): string[] {
        const reasons: string[] = [];
        rawReasons.forEach((reason) => {
            if (typeof reason === "string" && reason.trim()) {
                reasons.push(reason.trim());
                return;
            }
            if (reason && typeof reason === "object") {
                const feature = String(reason["feature"] || "").replace(/_/g, " ").trim();
                const direction = String(reason["direction"] || "").trim();
                if (!feature) return;
                if (direction === "decrease_risk") {
                    reasons.push(`${feature} is reducing risk`);
                } else {
                    reasons.push(`${feature} is increasing risk`);
                }
            }
        });
        return reasons.slice(0, 3);
    }

    private async convertAmount(
        amount: number,
        fromCurrency: string,
        toCurrency: string,
    ): Promise<number> {
        if (!Number.isFinite(amount) || amount <= 0) return 0;
        const from = String(fromCurrency || "").toUpperCase();
        const to = String(toCurrency || "").toUpperCase();
        if (!from || !to || from === to) return amount;

        try {
            const converted = await firstValueFrom(this.api.convertCurrency(amount, from, to));
            const direct = Number(converted?.converted_amount || 0);
            if (direct > 0) return direct;
            const rate = Number(converted?.rate || 0);
            if (rate > 0) return amount * rate;
        } catch {
            // Ignore API conversion failure and continue with local fallbacks.
        }

        if (from === this.userCurrencyCode && to === "USD") {
            return this.convertUserToUsd(amount);
        }
        if (from === "USD" && to === this.userCurrencyCode) {
            return this.convertUsdToUser(amount);
        }
        if (from === this.userCurrencyCode && to === "INR") {
            const usd = this.convertUserToUsd(amount);
            const usdToInr = await this.convertAmount(1, "USD", "INR");
            return usdToInr > 0 ? usd * usdToInr : amount;
        }
        if (from === "INR" && to === this.userCurrencyCode) {
            const inrToUsd = await this.convertAmount(1, "INR", "USD");
            const usd = inrToUsd > 0 ? amount * inrToUsd : amount;
            return this.convertUsdToUser(usd);
        }
        return amount;
    }

    private async refreshMlInsights(): Promise<void> {
        if (!this.connectedWallet || !this.form.amount || this.form.amount <= 0 || this.bnbPrice <= 0) {
            return;
        }

        const requestVersion = ++this.mlRequestVersion;
        this.mlInsightsError = "";
        this.mlRiskLoading = true;
        this.depositRecommendationLoading = true;
        this.defaultPredictionLoading = true;

        try {
            const amountUser = Number(this.form.amount || 0);
            const tenureDays = Math.max(1, this.form.installments * 30);
            const installmentAmountUser = amountUser / Math.max(1, this.form.installments);

            const planAmountInr = await this.convertAmount(amountUser, this.userCurrencyCode, "INR");
            const installmentAmountInr = await this.convertAmount(installmentAmountUser, this.userCurrencyCode, "INR");
            let bnbPriceInr = await this.convertAmount(this.bnbPrice, this.userCurrencyCode, "INR");
            if (bnbPriceInr <= 0 && this.bnbPriceUsd > 0) {
                bnbPriceInr = await this.convertAmount(this.bnbPriceUsd, "USD", "INR");
            }
            const inrToUserRate = await this.convertAmount(1, "INR", this.userCurrencyCode);
            const outstandingInr = Math.max(planAmountInr, installmentAmountInr);
            const collateralValueInr = Math.max(0, this.collateralRequired * bnbPriceInr);
            const safetyRatio = outstandingInr > 0 ? (collateralValueInr / outstandingInr) : 1;
            const onTimeRatio = this.getDerivedOnTimeRatio();
            const missedCount = Math.max(0, this.userLatePaymentCount);

            const riskPayload: RiskFeatureInput = {
                safety_ratio: Math.max(0.000001, safetyRatio),
                missed_payment_count: missedCount,
                on_time_ratio: onTimeRatio,
                avg_delay_hours: missedCount > 0 ? 12 : 0,
                topup_count_last_30d: Math.max(0, this.userTopupCount),
                plan_amount: Math.max(1, planAmountInr),
                tenure_days: tenureDays,
                installment_amount: Math.max(1, installmentAmountInr),
            };

            let mlRiskTier = this.riskTier;
            try {
                const score = await firstValueFrom(this.api.mlScore(riskPayload));
                if (requestVersion !== this.mlRequestVersion) return;
                mlRiskTier = String(score?.risk_tier || this.riskTier || "MEDIUM").toUpperCase();
                this.mlModelRiskTier = mlRiskTier;
                this.mlRiskProbabilities = score?.probabilities || {};
                this.mlRiskReasons = this.normalizeMlReasons(score?.top_reasons || []);
            } catch {
                if (requestVersion !== this.mlRequestVersion) return;
                this.mlModelRiskTier = String(this.riskTier || "MEDIUM").toUpperCase();
                this.mlRiskProbabilities = {};
                this.mlRiskReasons = [];
            } finally {
                if (requestVersion === this.mlRequestVersion) {
                    this.mlRiskLoading = false;
                }
            }

            const depositPayload: DepositRecommendationRequest = {
                plan_amount_inr: Math.max(1, planAmountInr),
                tenure_days: tenureDays,
                risk_tier: String(mlRiskTier || this.riskTier || "MEDIUM").toUpperCase(),
                collateral_token: "BNB",
                collateral_type: "volatile",
                locked_token: 0,
                price_inr: Math.max(1, bnbPriceInr),
                outstanding_debt_inr: Math.max(1, outstandingInr),
            };

            const [policyResult, mlResult] = await Promise.all([
                firstValueFrom(this.api.recommendDepositPolicy(depositPayload)).catch(() => null),
                firstValueFrom(this.api.recommendDepositMl(depositPayload)).catch(() => null),
            ]);

            if (requestVersion !== this.mlRequestVersion) return;
            this.depositPolicyRecommendation = policyResult;
            this.depositMlRecommendation = mlResult;
            this.depositPolicyRequiredUser = policyResult ? Number(policyResult.required_inr || 0) * inrToUserRate : 0;
            this.depositMlRequiredUser = mlResult ? Number(mlResult.required_inr || 0) * inrToUserRate : 0;
            this.depositRecommendationLoading = false;

            const defaultPayload: DefaultPredictionRequest = {
                user_id: this.userId,
                plan_id: `sim-${this.userId || "user"}-${Date.now()}`,
                installment_id: "installment-1",
                cutoff_at: new Date().toISOString(),
                on_time_ratio: onTimeRatio,
                missed_count_90d: missedCount,
                max_days_late_180d: missedCount > 0 ? 3 : 0,
                avg_days_late: missedCount > 0 ? 1.5 : 0,
                days_since_last_late: missedCount > 0 ? 7 : 90,
                consecutive_on_time_count: Math.max(0, this.userOnTimePaymentCount),
                plan_amount: Math.max(1, planAmountInr),
                tenure_days: tenureDays,
                installment_amount: Math.max(1, installmentAmountInr),
                installment_number: 1,
                days_until_due: 30,
                current_safety_ratio: Math.max(0.000001, safetyRatio),
                distance_to_liquidation_threshold: Math.max(-5, safetyRatio - 1),
                collateral_type: "volatile",
                collateral_volatility_bucket: "high",
                topup_count_30d: Math.max(0, this.userTopupCount),
                topup_recency_days: this.userTopupCount > 0 ? 7 : 30,
                opened_app_last_7d: 1,
                clicked_pay_now_last_7d: 0,
                payment_attempt_failed_count: missedCount > 0 ? 1 : 0,
                wallet_age_days: Math.max(1, this.userWalletAgeDays),
                tx_count_30d: Math.max(1, this.userOnTimePaymentCount + this.userLatePaymentCount),
                stablecoin_balance_bucket: safetyRatio > 1.35 ? "high" : "medium",
            };

            try {
                const prediction = await firstValueFrom(this.api.predictDefault(defaultPayload));
                if (requestVersion !== this.mlRequestVersion) return;
                this.defaultPrediction = prediction;
            } catch {
                if (requestVersion !== this.mlRequestVersion) return;
                this.defaultPrediction = null;
            } finally {
                if (requestVersion === this.mlRequestVersion) {
                    this.defaultPredictionLoading = false;
                }
            }
        } catch {
            if (requestVersion === this.mlRequestVersion) {
                this.mlInsightsError = "Unable to refresh ML insights right now.";
                this.mlRiskLoading = false;
                this.depositRecommendationLoading = false;
                this.defaultPredictionLoading = false;
            }
        }
    }

    ngOnDestroy(): void {
        if (this.riskRefreshTimer) {
            clearTimeout(this.riskRefreshTimer);
            this.riskRefreshTimer = null;
        }
    }

    private buildPath(): void {
        if (!this.priceHistory.length) {
            this.svgPath = "";
            return;
        }
        const range = this.chartMax - this.chartMin || 1;
        const xStep = this.chartW / (this.POINTS - 1);
        const points = this.priceHistory.map((price, index) => {
            const x = index * xStep;
            const y = this.chartH - ((price - this.chartMin) / range) * this.chartH;
            return `${x.toFixed(1)},${y.toFixed(1)}`;
        });
        this.svgPath = `M ${points.join(" L ")}`;
    }

    async connectMetaMask(): Promise<void> {
        this.walletValidationError = "";
        const provider = (window as unknown as { ethereum?: EthereumProvider }).ethereum;
        if (!provider) {
            this.walletValidationError = "MetaMask is not available in this browser.";
            return;
        }

        this.isConnectingWallet = true;
        try {
            const accounts = (await provider.request({ method: "eth_requestAccounts" })) as string[];
            const account = accounts?.[0] || "";
            this.connectedWallet = account;
            sessionStorage.setItem("connected_wallet", account);
            this.validateConnectedWallet();
            this.loadRiskScore();
        } catch {
            this.walletValidationError = "Wallet connection was rejected.";
        } finally {
            this.isConnectingWallet = false;
        }
    }

    private validateConnectedWallet(): void {
        if (!this.connectedWallet) return;
        this.walletValidating = true;
        this.walletValidationError = "";
        this.api.validateWallet(this.connectedWallet).subscribe({
            next: (res) => {
                this.walletValidating = false;
                if (!res.is_valid) {
                    this.walletValidationError = "Connected wallet address is invalid.";
                    return;
                }
                if (res.checksum_address) {
                    this.connectedWallet = res.checksum_address;
                    sessionStorage.setItem("connected_wallet", this.connectedWallet);
                }
            },
            error: () => {
                this.walletValidating = false;
                this.walletValidationError = "Unable to validate wallet with backend.";
            },
        });
    }

    private setRepaymentDate(): void {
        const date = new Date();
        date.setMonth(date.getMonth() + this.form.installments);
        this.form.repaymentDate = date.toISOString().split("T")[0];
    }

    onInstallmentsChange(): void {
        this.setRepaymentDate();
        this.scheduleRiskRefresh(120);
    }

    toggleNotification(key: string): void {
        const index = this.form.notifications.indexOf(key);
        if (index >= 0) {
            if (this.form.notifications.length === 1) return;
            this.form.notifications.splice(index, 1);
        } else {
            this.form.notifications.push(key);
        }
    }

    isNotifActive(key: string): boolean {
        return this.form.notifications.includes(key);
    }

    submit(): void {
        if (!this.isValid) return;
        sessionStorage.setItem("borrow_form", JSON.stringify(this.form));
        sessionStorage.setItem("connected_wallet", this.connectedWallet);
        this.router.navigate(["/transaction"], {
            state: {
                userId: this.userId,
                loanName: this.form.loanName,
                amount: this.form.amount,
                installments: this.form.installments,
                repaymentDate: this.form.repaymentDate,
                notifications: this.form.notifications,
                emiAmount: this.emiAmount,
                liquidationPrice: this.liquidationPrice,
                collateralRequired: this.collateralRequired,
                bnbPrice: this.bnbPrice,
                bnbPriceUsd: this.bnbPriceUsd,
                walletAddress: this.connectedWallet,
                currencyCode: this.userCurrencyCode,
                currencySymbol: this.userCurrencySymbol,
            },
        });
    }

    goBack(): void {
        sessionStorage.removeItem("borrow_form");
        this.router.navigate(["/board"]);
    }
}
