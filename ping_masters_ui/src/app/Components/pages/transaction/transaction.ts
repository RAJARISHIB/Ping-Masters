import { Component, OnInit, OnDestroy, ChangeDetectorRef } from "@angular/core";
import { Router } from "@angular/router";
import { FormsModule } from "@angular/forms";
import { firstValueFrom } from "rxjs";
import { SharedModule } from "../../../app.module";
import { ApiService } from "../../../services/api.service";
import { CurrencySymbolService } from "../../../services/currency-symbol.service";

interface LoanSummary {
    userId?: string;
    loanName: string;
    amount: number;
    installments: number;
    repaymentDate: string;
    notifications: string[];
    emiAmount: number;
    liquidationPrice: number;
    collateralRequired: number;
    bnbPrice: number;
    bnbPriceUsd?: number;
    walletAddress?: string;
    currencyCode?: string;
    currencySymbol?: string;
}

interface Wallet {
    address: string;
    bnbBalance: number;
    label: string;
}

interface BankAccount {
    id: string;
    bank: string;
    accountNumber: string;
    displayNumber: string;
    ifsc: string;
    name: string;
}

interface Toaster {
    id: number;
    type: "info" | "success" | "warning" | "error";
    title: string;
    message: string;
    visible: boolean;
}

interface TxStep {
    label: string;
    sublabel: string;
    done: boolean;
    active: boolean;
    failed: boolean;
}

@Component({
    selector: "app-transaction",
    templateUrl: "./transaction.html",
    styleUrls: ["./transaction.scss"],
    standalone: true,
    imports: [SharedModule, FormsModule],
})
export class Transaction implements OnInit, OnDestroy {
    loan: LoanSummary | null = null;

    wallets: Wallet[] = [];
    selectedWalletAddress = "";
    walletsLoading = false;

    bankAccounts: BankAccount[] = [
        {
            id: "ba-001",
            bank: "State Bank of India",
            accountNumber: "123400004521",
            displayNumber: "****4521",
            ifsc: "SBIN0001234",
            name: "Primary Savings",
        },
        {
            id: "ba-002",
            bank: "HDFC Bank",
            accountNumber: "987600008892",
            displayNumber: "****8892",
            ifsc: "HDFC0004567",
            name: "Salary Account",
        },
    ];
    selectedBankId = "ba-001";

    showAddBankForm = false;
    newBank = {
        accountHolder: "",
        bankName: "",
        accountNumber: "",
        confirmAccountNumber: "",
        ifsc: "",
    };

    txStatus: "idle" | "processing" | "success" | "failed" = "idle";
    showConfirmDialog = false;
    steps: TxStep[] = [
        { label: "Initiating transaction", sublabel: "Broadcasting to blockchain network", done: false, active: false, failed: false },
        { label: "Locking BNB collateral", sublabel: "Executing smart contract deposit", done: false, active: false, failed: false },
        { label: "Smart contract approval", sublabel: "Verifying collateral ratio and credit", done: false, active: false, failed: false },
        { label: "Transfer to bank", sublabel: "Disbursing funds to linked account", done: false, active: false, failed: false },
    ];
    currentStep = -1;

    toasters: Toaster[] = [];
    private toastCounter = 0;
    private timers: any[] = [];

    userCurrencyCode = "USD";
    userCurrencySymbol = "$";

    get newBankValid(): boolean {
        return !!(
            this.newBank.accountHolder.trim() &&
            this.newBank.bankName.trim() &&
            this.newBank.accountNumber.trim().length >= 9 &&
            this.newBank.accountNumber === this.newBank.confirmAccountNumber &&
            this.newBank.ifsc.trim().length === 11
        );
    }

    get selectedWallet(): Wallet | undefined {
        return this.wallets.find((w) => w.address === this.selectedWalletAddress);
    }

    get selectedBank(): BankAccount | undefined {
        return this.bankAccounts.find((b) => b.id === this.selectedBankId);
    }

    get hasBankAccounts(): boolean {
        return this.bankAccounts.length > 0;
    }

    get currencySymbol(): string {
        return this.loan?.currencySymbol || this.userCurrencySymbol;
    }

    get walletHasSufficientBnb(): boolean {
        return !this.loan || !this.selectedWallet
            ? false
            : this.selectedWallet.bnbBalance >= this.loan.collateralRequired;
    }

    get canConfirm(): boolean {
        return (
            this.txStatus === "idle" &&
            !!this.selectedWalletAddress &&
            (this.hasBankAccounts ? !!this.selectedBankId : false) &&
            this.walletHasSufficientBnb
        );
    }

    constructor(
        public router: Router,
        private cdr: ChangeDetectorRef,
        private api: ApiService,
        private currencySymbols: CurrencySymbolService,
    ) {}

    ngOnInit(): void {
        this.userCurrencySymbol = this.currencySymbols.resolveSymbol(this.userCurrencyCode);
        this.loadUserCurrencyContext();

        const state = history.state as Partial<LoanSummary>;
        if (state?.amount) {
            const fallbackCurrencyCode = String(state.currencyCode || this.userCurrencyCode || "USD").toUpperCase();
            this.loan = {
                loanName: state.loanName ?? "Unnamed Loan",
                amount: state.amount ?? 0,
                installments: state.installments ?? 6,
                repaymentDate: state.repaymentDate ?? "",
                notifications: state.notifications ?? [],
                emiAmount: state.emiAmount ?? 0,
                liquidationPrice: state.liquidationPrice ?? 0,
                collateralRequired: state.collateralRequired ?? 0,
                bnbPrice: state.bnbPrice ?? 0,
                bnbPriceUsd: state.bnbPriceUsd ?? 0,
                walletAddress: state.walletAddress,
                currencyCode: fallbackCurrencyCode,
                currencySymbol: state.currencySymbol ?? this.currencySymbols.resolveSymbol(fallbackCurrencyCode, this.userCurrencyCode),
            };
        }

        this.selectedWalletAddress = state.walletAddress || sessionStorage.getItem("connected_wallet") || "";
        this.loadWallets();

        if (!this.hasBankAccounts) {
            this.showAddBankForm = true;
        }
    }

    ngOnDestroy(): void {
        this.timers.forEach((timer) => clearTimeout(timer));
    }

    private loadUserCurrencyContext(): void {
        const userId = sessionStorage.getItem("user_id") || "";
        if (!userId) return;

        this.api.getUser(userId).subscribe({
            next: (user) => {
                const code = String(user?.currency_code || this.userCurrencyCode || "USD").toUpperCase();
                this.userCurrencyCode = code;
                this.userCurrencySymbol = this.currencySymbols.resolveSymbol(code);

                if (this.loan) {
                    const loanCurrencyCode = String(this.loan.currencyCode || code).toUpperCase();
                    this.loan.currencyCode = loanCurrencyCode;
                    this.loan.currencySymbol = this.currencySymbols.resolveSymbol(loanCurrencyCode, code);
                }
            },
            error: () => {
                this.userCurrencyCode = "USD";
                this.userCurrencySymbol = this.currencySymbols.resolveSymbol("USD");
            },
        });
    }

    private loadWallets(): void {
        const userId = sessionStorage.getItem("user_id") || "user_001";
        const connectedWallet = this.selectedWalletAddress;
        this.walletsLoading = true;

        this.api.getUserWallets(userId).subscribe({
            next: (res) => {
                let wallets = (res.wallet_address || []).map((entry, index) => ({
                    address: entry.wallet_id,
                    bnbBalance: 0,
                    label: entry.name || `Wallet ${index + 1}`,
                }));

                if (connectedWallet) {
                    wallets = wallets.filter((wallet) => wallet.address.toLowerCase() === connectedWallet.toLowerCase());
                }

                if (!wallets.length && connectedWallet) {
                    wallets.push({
                        address: connectedWallet,
                        bnbBalance: 0,
                        label: "Connected Wallet",
                    });
                }

                this.wallets = wallets;
                if (!this.selectedWalletAddress && this.wallets.length) {
                    this.selectedWalletAddress = this.wallets[0].address;
                }
                this.loadWalletBalances();
            },
            error: () => {
                this.wallets = connectedWallet
                    ? [{ address: connectedWallet, bnbBalance: 0, label: "Connected Wallet" }]
                    : [];
                this.loadWalletBalances();
            },
        });
    }

    private loadWalletBalances(): void {
        if (!this.wallets.length) {
            this.walletsLoading = false;
            return;
        }

        const pending = this.wallets.map((wallet) =>
            firstValueFrom(this.api.getWalletBalance(wallet.address, "bsc"))
                .then((res) => ({ address: wallet.address, balance: Number(res.balance_bnb || 0) }))
                .catch(() => ({ address: wallet.address, balance: 0 }))
        );

        Promise.all(pending).then((rows) => {
            this.wallets = this.wallets.map((wallet) => {
                const row = rows.find((item) => item.address === wallet.address);
                return { ...wallet, bnbBalance: row?.balance ?? 0 };
            });
            this.walletsLoading = false;
            this.cdr.detectChanges();
        });
    }

    goBack(): void {
        if (this.txStatus === "success") {
            sessionStorage.removeItem("borrow_form");
            this.router.navigate(["/board"]);
            return;
        }
        this.router.navigate(["/borrow"]);
    }

    saveNewBank(): void {
        if (!this.newBankValid) return;
        const last4 = this.newBank.accountNumber.slice(-4);
        const newBank: BankAccount = {
            id: `ba-new-${Date.now()}`,
            bank: this.newBank.bankName,
            accountNumber: this.newBank.accountNumber,
            displayNumber: `****${last4}`,
            ifsc: this.newBank.ifsc.toUpperCase(),
            name: this.newBank.accountHolder,
        };
        this.bankAccounts.push(newBank);
        this.selectedBankId = newBank.id;
        this.showAddBankForm = false;
        this.newBank = { accountHolder: "", bankName: "", accountNumber: "", confirmAccountNumber: "", ifsc: "" };
    }

    confirmTransaction(): void {
        if (!this.canConfirm || !this.loan) return;
        this.showConfirmDialog = true;
    }

    cancelConfirm(): void {
        this.showConfirmDialog = false;
    }

    executeTransaction(): void {
        if (!this.canConfirm || !this.loan) return;
        this.showConfirmDialog = false;
        this.txStatus = "processing";
        this.runBnplFlow().catch(() => {
            this.txStatus = "failed";
            this.pushToast("error", "Transaction failed", "Backend API failed while executing the BNPL flow.");
        });
    }

    private setStep(index: number): void {
        this.currentStep = index;
        this.steps[index].active = true;
        this.steps[index].done = false;
        this.cdr.detectChanges();
    }

    private completeStep(index: number): void {
        this.steps[index].active = false;
        this.steps[index].done = true;
        this.cdr.detectChanges();
    }

    private delay(ms: number): Promise<void> {
        return new Promise((resolve) => {
            const timer = setTimeout(resolve, ms);
            this.timers.push(timer);
        });
    }

    private async runBnplFlow(): Promise<void> {
        const loan = this.loan!;
        const wallet = this.selectedWallet;
        const userId = sessionStorage.getItem("user_id") || "user_001";
        const principalMinor = ApiService.toPaise(loan.amount);
        const currencyCode = loan.currencyCode || this.userCurrencyCode || "USD";
        const collateralBnb = loan.collateralRequired;
        const oraclePriceMinor = ApiService.toPaise(loan.bnbPrice);

        this.setStep(0);
        const planRes = await firstValueFrom(this.api.createBnplPlan({
            user_id: userId,
            merchant_id: "merchant_001",
            principal_minor: principalMinor,
            currency: currencyCode,
            installment_count: loan.installments,
            tenure_days: loan.installments * 30,
            ltv_bps: 6667,
            collateral_asset: "BNB",
            oracle_price_minor: oraclePriceMinor,
        }));
        const loanId: string = (planRes as any)?.loan?.id ?? `loan-${Date.now()}`;
        await this.delay(900);
        this.completeStep(0);

        this.setStep(1);
        await firstValueFrom(this.api.lockCollateral({
            loan_id: loanId,
            user_id: userId,
            asset_symbol: "BNB",
            deposited_units: collateralBnb,
            collateral_value_minor: Math.round(collateralBnb * oraclePriceMinor),
            oracle_price_minor: oraclePriceMinor,
            vault_address: wallet?.address ?? "0x0000",
            chain_id: "97",
            deposit_tx_hash: `0xsimulated${Date.now()}`,
        }));
        await this.delay(900);
        this.completeStep(1);

        this.setStep(2);
        await firstValueFrom(this.api.createAutopayMandate({
            user_id: userId,
            loan_id: loanId,
            amount_minor: ApiService.toPaise(loan.emiAmount),
            currency: currencyCode,
        }));
        await this.delay(900);
        this.completeStep(2);

        this.setStep(3);
        const razorpayStatus = await firstValueFrom(this.api.getRazorpayStatus());
        if (!razorpayStatus.available) {
            throw new Error("Razorpay is unavailable");
        }
        await this.api.openRazorpayCheckout(
            principalMinor,
            currencyCode,
            `Loan disbursement - ${loan.loanName}`,
            undefined,
            { keyId: String(razorpayStatus.checkout_key_id || "").trim() },
        );
        await this.delay(600);
        this.completeStep(3);

        this.txStatus = "success";
        this.currentStep = 4;
        this.cdr.detectChanges();
        this.fireToasters();

        const navTimer = setTimeout(() => {
            sessionStorage.removeItem("borrow_form");
            this.router.navigate(["/board"]);
        }, 6000);
        this.timers.push(navTimer);
    }

    private pushToast(type: Toaster["type"], title: string, message: string): void {
        const id = ++this.toastCounter;
        this.toasters.push({ id, type, title, message, visible: true });
        this.cdr.detectChanges();
        const dismissTimer = setTimeout(() => {
            const toast = this.toasters.find((entry) => entry.id === id);
            if (toast) toast.visible = false;
            this.cdr.detectChanges();
            setTimeout(() => {
                this.toasters = this.toasters.filter((entry) => entry.id !== id);
                this.cdr.detectChanges();
            }, 400);
        }, 5000);
        this.timers.push(dismissTimer);
    }

    private fireToasters(): void {
        if (!this.loan) return;
        const bank = this.selectedBank;
        const wallet = this.selectedWallet;
        const msgs: { delay: number; type: Toaster["type"]; title: string; message: string }[] = [
            {
                delay: 200,
                type: "info",
                title: "Transaction Submitted",
                message: "Broadcasting to BNB Smart Chain...",
            },
            {
                delay: 1600,
                type: "info",
                title: "Collateral Locked",
                message: `${this.loan.collateralRequired} BNB locked from ${wallet?.label ?? "wallet"}`,
            },
            {
                delay: 3200,
                type: "success",
                title: "Contract Approved",
                message: "Loan smart contract executed successfully",
            },
            {
                delay: 4800,
                type: "success",
                title: "Funds Disbursed",
                message: `${this.currencySymbol}${this.loan.amount.toLocaleString("en-IN")} transferred to ${bank?.bank ?? "your bank"} ${bank?.displayNumber ?? ""}`,
            },
        ];

        msgs.forEach(({ delay, type, title, message }) => {
            const timer = setTimeout(() => {
                const id = ++this.toastCounter;
                this.toasters.push({ id, type, title, message, visible: true });
                this.cdr.detectChanges();
                const dismissTimer = setTimeout(() => {
                    const toast = this.toasters.find((entry) => entry.id === id);
                    if (toast) toast.visible = false;
                    this.cdr.detectChanges();
                    setTimeout(() => {
                        this.toasters = this.toasters.filter((entry) => entry.id !== id);
                        this.cdr.detectChanges();
                    }, 400);
                }, 4000);
                this.timers.push(dismissTimer);
            }, delay);
            this.timers.push(timer);
        });
    }

    dismissToast(id: number): void {
        const toast = this.toasters.find((entry) => entry.id === id);
        if (toast) toast.visible = false;
        this.cdr.detectChanges();
        setTimeout(() => {
            this.toasters = this.toasters.filter((entry) => entry.id !== id);
            this.cdr.detectChanges();
        }, 400);
    }

    formatAddress(addr: string): string {
        return `${addr.slice(0, 6)}...${addr.slice(-4)}`;
    }
}
