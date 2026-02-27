import { Component, OnInit, OnDestroy } from "@angular/core";
import { Router } from "@angular/router";
import { FormsModule } from "@angular/forms";
import { SharedModule } from "../../../app.module";
import { ApiService } from "../../../services/api.service";

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

    // ── BNB chart ──────────────────────────────────────────────
    readonly chartW = 600;
    readonly chartH = 140;
    readonly POINTS = 60;

    bnbPrice = 298.4;
    bnbHigh = 312.5;
    bnbLow = 281.2;
    bnbChange = -1.4;
    priceHistory: number[] = [];
    svgPath = "";
    chartMin = 265;
    chartMax = 335;

    // ── User stats ─────────────────────────────────────────────
    creditScore = 742;
    riskTier = "MEDIUM";
    creditScoreLoading = false;
    minBorrow = 500;
    maxBorrow = 50000;

    // ── Wallet / eligibility ──────────────────────────────────
    connectedWallet = "";
    walletValidationError = "";
    walletValidating = false;
    isConnectingWallet = false;
    eligibilityLoading = false;
    eligibilityAvailableCredit = 0;
    eligibilityLtvBps = 0;

    // ── Form ───────────────────────────────────────────────────
    form: BorrowForm = {
        loanName: "",
        amount: null,
        installments: 6,
        repaymentDate: "",
        notifications: ["email"],
    };

    /** Installment months: from API (GET /bnpl/emi/plans) or fallback when API unavailable */
    installmentOptions: number[] = [3, 6, 12, 24];
    notificationChannels = [
        { key: "email",    icon: "fa-solid fa-envelope",    label: "Email" },
        { key: "whatsapp", icon: "fa-brands fa-whatsapp",   label: "WhatsApp" },
        { key: "phone",    icon: "fa-solid fa-phone",        label: "Phone" },
        { key: "telegram", icon: "fa-brands fa-telegram",   label: "Telegram" },
    ];

    // ── Computed ───────────────────────────────────────────────
    get emiAmount(): number {
        if (!this.form.amount || !this.form.installments) return 0;
        const interest = 0.12 / 12;
        const n = this.form.installments;
        const p = this.form.amount;
        return Math.ceil(p * interest * Math.pow(1 + interest, n) / (Math.pow(1 + interest, n) - 1));
    }

    get liquidationPrice(): number {
        if (!this.form.amount) return 0;
        // Liquidation when collateral value drops to 120% of loan
        const collateralBnb = (this.form.amount * 1.5) / this.bnbPrice;
        return parseFloat(((this.form.amount * 1.2) / collateralBnb).toFixed(2));
    }

    get collateralRequired(): number {
        if (!this.form.amount) return 0;
        return parseFloat(((this.form.amount * 1.5) / this.bnbPrice).toFixed(4));
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

    constructor(private router: Router, private api: ApiService) {}

    ngOnInit(): void {
        // Restore form if user came back from transaction page
        const saved = sessionStorage.getItem('borrow_form');
        if (saved) {
            try { this.form = { ...this.form, ...JSON.parse(saved) }; } catch {}
        }

        // Set default repayment date only if not restored
        if (!this.form.repaymentDate) {
            const d = new Date();
            d.setMonth(d.getMonth() + this.form.installments);
            this.form.repaymentDate = d.toISOString().split("T")[0];
        }

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

    private loadEmiPlans(): void {
        this.api.getBnplEmiPlans("INR", false).subscribe({
            next: (res) => {
                if (res.plans && res.plans.length > 0) {
                    const counts = res.plans
                        .map((p) => p.installment_count)
                        .filter((n) => Number.isInteger(n) && n > 0);
                    const unique = [...new Set(counts)].sort((a, b) => a - b);
                    if (unique.length > 0) {
                        this.installmentOptions = unique;
                        if (!this.form.installments || !this.installmentOptions.includes(this.form.installments)) {
                            this.form.installments = this.installmentOptions[0];
                            const d = new Date();
                            d.setMonth(d.getMonth() + this.form.installments);
                            this.form.repaymentDate = d.toISOString().split("T")[0];
                        }
                    }
                }
            },
            error: () => {
                // Keep default [3, 6, 12, 24]
            },
        });
    }

    private loadEligibility(): void {
        const userId = sessionStorage.getItem("user_id") || "user_001";
        this.eligibilityLoading = true;
        this.api.getBnplEligibility(userId).subscribe({
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
        this.api.getBnbChart('1D').subscribe({
            next: (res) => {
                if (!res.prices || res.prices.length === 0) return;
                const prices = res.prices.map(([, price]) => Number(price)).filter((price) => Number.isFinite(price));
                if (prices.length === 0) return;
                this.bnbPrice = prices[prices.length - 1];
                this.priceHistory = prices.slice(-this.POINTS);
                while (this.priceHistory.length < this.POINTS) {
                    this.priceHistory.unshift(this.priceHistory[0]);
                }
                this.bnbHigh = Math.max(...this.priceHistory);
                this.bnbLow = Math.min(...this.priceHistory);
                this.chartMin = Math.max(1, this.bnbLow * 0.98);
                this.chartMax = this.bnbHigh * 1.02;
                const first = this.priceHistory[0] || this.bnbPrice;
                this.bnbChange = parseFloat((((this.bnbPrice - first) / first) * 100).toFixed(2));
                this.buildPath();
                this.loadRiskScore();
            },
            error: () => {
                this.priceHistory = [];
                this.svgPath = "";
            },
        });
    }

    loadRiskScore(): void {
        if (!this.connectedWallet) {
            return;
        }

        this.creditScoreLoading = true;
        this.api.predictRisk({
            wallet_address: this.connectedWallet,
            collateral_bnb: this.collateralRequired || 1.5,
            debt_fiat: this.form.amount ?? 10000,
            current_price: this.bnbPrice,
        }).subscribe({
            next: (res) => {
                this.creditScoreLoading = false;
                this.riskTier = res.prediction?.risk_tier ?? "MEDIUM";
                const prob = res.prediction?.liquidation_probability ?? 0.3;
                // Map liquidation probability to a 300–900 credit score
                this.creditScore = Math.round(900 - prob * 600);
            },
            error: () => {
                this.creditScoreLoading = false;
            },
        });
    }

    ngOnDestroy(): void {
    }

    private buildPath(): void {
        if (!this.priceHistory.length) {
            this.svgPath = "";
            return;
        }
        const range = this.chartMax - this.chartMin || 1;
        const xStep = this.chartW / (this.POINTS - 1);
        const pts = this.priceHistory.map((price, i) => {
            const x = i * xStep;
            const y = this.chartH - ((price - this.chartMin) / range) * this.chartH;
            return `${x.toFixed(1)},${y.toFixed(1)}`;
        });
        this.svgPath = `M ${pts.join(" L ")}`;
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

    onInstallmentsChange(): void {
        const d = new Date();
        d.setMonth(d.getMonth() + this.form.installments);
        this.form.repaymentDate = d.toISOString().split("T")[0];
        this.loadRiskScore();
    }

    toggleNotification(key: string): void {
        const idx = this.form.notifications.indexOf(key);
        if (idx >= 0) {
            if (this.form.notifications.length === 1) return; // keep at least 1
            this.form.notifications.splice(idx, 1);
        } else {
            this.form.notifications.push(key);
        }
    }

    isNotifActive(key: string): boolean {
        return this.form.notifications.includes(key);
    }

    submit(): void {
        if (!this.isValid) return;
        // Persist form so state is restored if user navigates back
        sessionStorage.setItem('borrow_form', JSON.stringify(this.form));
        sessionStorage.setItem('connected_wallet', this.connectedWallet);
        this.router.navigate(["/transaction"], {
            state: {
                loanName: this.form.loanName,
                amount: this.form.amount,
                installments: this.form.installments,
                repaymentDate: this.form.repaymentDate,
                notifications: this.form.notifications,
                emiAmount: this.emiAmount,
                liquidationPrice: this.liquidationPrice,
                collateralRequired: this.collateralRequired,
                bnbPrice: this.bnbPrice,
                walletAddress: this.connectedWallet,
            }
        });
    }

    goBack(): void {
        sessionStorage.removeItem('borrow_form');
        this.router.navigate(["/board"]);
    }
}
