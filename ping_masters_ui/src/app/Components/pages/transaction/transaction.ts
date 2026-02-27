import { Component, OnInit, OnDestroy, ChangeDetectorRef } from "@angular/core";
import { Router } from "@angular/router";
import { FormsModule } from "@angular/forms";
import { firstValueFrom } from "rxjs";
import { SharedModule } from "../../../app.module";
import { ApiService } from "../../../services/api.service";

interface LoanSummary {
    loanName: string;
    amount: number;
    installments: number;
    repaymentDate: string;
    notifications: string[];
    emiAmount: number;
    liquidationPrice: number;
    collateralRequired: number;
    bnbPrice: number;
    walletAddress?: string;
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

    // ── Loan data from router state ────────────────────────────
    loan: LoanSummary | null = null;

    // ── Wallets ────────────────────────────────────────────────
    wallets: Wallet[] = [];
    selectedWalletAddress = "";
    walletsLoading = false;

    // ── Bank accounts ──────────────────────────────────────────
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

    // ── Add bank form (shown when no bank accounts) ────────────
    showAddBankForm = false;
    newBank = {
        accountHolder: "",
        bankName: "",
        accountNumber: "",
        confirmAccountNumber: "",
        ifsc: "",
    };
    get newBankValid(): boolean {
        return !!(
            this.newBank.accountHolder.trim() &&
            this.newBank.bankName.trim() &&
            this.newBank.accountNumber.trim().length >= 9 &&
            this.newBank.accountNumber === this.newBank.confirmAccountNumber &&
            this.newBank.ifsc.trim().length === 11
        );
    }

    // ── Transaction state ──────────────────────────────────────
    txStatus: "idle" | "processing" | "success" | "failed" = "idle";
    showConfirmDialog = false;
    steps: TxStep[] = [
        { label: "Initiating transaction", sublabel: "Broadcasting to blockchain network", done: false, active: false, failed: false },
        { label: "Locking BNB collateral", sublabel: "Executing smart contract deposit", done: false, active: false, failed: false },
        { label: "Smart contract approval", sublabel: "Verifying collateral ratio & credit", done: false, active: false, failed: false },
        { label: "INR transfer to bank", sublabel: "Disbursing funds to linked account", done: false, active: false, failed: false },
    ];
    currentStep = -1;

    // ── Toasters ───────────────────────────────────────────────
    toasters: Toaster[] = [];
    private toastCounter = 0;
    private timers: any[] = [];

    // ── Helpers ────────────────────────────────────────────────
    get selectedWallet(): Wallet | undefined {
        return this.wallets.find(w => w.address === this.selectedWalletAddress);
    }
    get selectedBank(): BankAccount | undefined {
        return this.bankAccounts.find(b => b.id === this.selectedBankId);
    }
    get hasBankAccounts(): boolean {
        return this.bankAccounts.length > 0;
    }
    get walletHasSufficientBnb(): boolean {
        return !this.loan || !this.selectedWallet
            ? false
            : this.selectedWallet.bnbBalance >= (this.loan.collateralRequired);
    }
    get canConfirm(): boolean {
        return (
            this.txStatus === "idle" &&
            !!this.selectedWalletAddress &&
            (this.hasBankAccounts ? !!this.selectedBankId : false) &&
            this.walletHasSufficientBnb
        );
    }

    constructor(public router: Router, private cdr: ChangeDetectorRef, private api: ApiService) {}

    ngOnInit(): void {
        const state = history.state as Partial<LoanSummary>;
        if (state?.amount) {
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
                walletAddress: state.walletAddress,
            };
        }
        this.selectedWalletAddress = state.walletAddress || sessionStorage.getItem("connected_wallet") || "";
        this.loadWallets();
        // If no bank accounts, default show add form
        if (!this.hasBankAccounts) {
            this.showAddBankForm = true;
        }
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

    ngOnDestroy(): void {
        this.timers.forEach(t => clearTimeout(t));
    }

    goBack(): void {
        if (this.txStatus === 'success') {
            sessionStorage.removeItem('borrow_form');
            this.router.navigate(["/board"]);
            return;
        }
        this.router.navigate(["/borrow"]);
    }

    saveNewBank(): void {
        if (!this.newBankValid) return;
        const last4 = this.newBank.accountNumber.slice(-4);
        const nb: BankAccount = {
            id: "ba-new-" + Date.now(),
            bank: this.newBank.bankName,
            accountNumber: this.newBank.accountNumber,
            displayNumber: "****" + last4,
            ifsc: this.newBank.ifsc.toUpperCase(),
            name: this.newBank.accountHolder,
        };
        this.bankAccounts.push(nb);
        this.selectedBankId = nb.id;
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

    private setStep(i: number): void {
        this.currentStep = i;
        this.steps[i].active = true;
        this.steps[i].done = false;
        this.cdr.detectChanges();
    }

    private completeStep(i: number): void {
        this.steps[i].active = false;
        this.steps[i].done = true;
        this.cdr.detectChanges();
    }

    private delay(ms: number): Promise<void> {
        return new Promise((res) => {
            const t = setTimeout(res, ms);
            this.timers.push(t);
        });
    }

    private async runBnplFlow(): Promise<void> {
        const loan = this.loan!;
        const wallet = this.selectedWallet;
        const userId = sessionStorage.getItem("user_id") || "user_001";
        const principalMinor = ApiService.toPaise(loan.amount);
        const collateralBnb = loan.collateralRequired;
        const oraclePriceMinor = ApiService.toPaise(loan.bnbPrice);

        // ── Step 1: Create BNPL plan ──────────────────────────
        this.setStep(0);
        const planRes = await firstValueFrom(this.api
            .createBnplPlan({
                user_id: userId,
                merchant_id: "merchant_001",
                principal_minor: principalMinor,
                currency: "INR",
                installment_count: loan.installments,
                tenure_days: loan.installments * 30,
                ltv_bps: 6667,   // 66.67% LTV
                collateral_asset: "BNB",
                oracle_price_minor: oraclePriceMinor,
            }));

        const loanId: string = (planRes as any)?.loan?.id ?? "loan-" + Date.now();
        await this.delay(900);
        this.completeStep(0);

        // ── Step 2: Lock collateral ───────────────────────────
        this.setStep(1);
        await firstValueFrom(this.api
            .lockCollateral({
                loan_id: loanId,
                user_id: userId,
                asset_symbol: "BNB",
                deposited_units: collateralBnb,
                collateral_value_minor: Math.round(collateralBnb * oraclePriceMinor),
                oracle_price_minor: oraclePriceMinor,
                vault_address: wallet?.address ?? "0x0000",
                chain_id: "97",    // BSC testnet
                deposit_tx_hash: "0xsimulated" + Date.now(),
            }));
        await this.delay(900);
        this.completeStep(1);

        // ── Step 3: Create autopay mandate ───────────────────
        this.setStep(2);
        await firstValueFrom(this.api
            .createAutopayMandate({
                user_id: userId,
                loan_id: loanId,
                amount_minor: ApiService.toPaise(loan.emiAmount),
                currency: "INR",
            }));
        await this.delay(900);
        this.completeStep(2);

        // ── Step 4: Razorpay checkout for INR disbursement ───
        this.setStep(3);
        const razorpayStatus = await firstValueFrom(this.api.getRazorpayStatus());
        if (!razorpayStatus.available) {
            throw new Error("Razorpay is unavailable");
        }
        await this.api.openRazorpayCheckout(
            principalMinor,
            `Loan disbursement — ${loan.loanName}`,
        );
        await this.delay(600);
        this.completeStep(3);

        // ── Success ──────────────────────────────────────────
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
        const dt = setTimeout(() => {
            const toast = this.toasters.find(x => x.id === id);
            if (toast) toast.visible = false;
            this.cdr.detectChanges();
            setTimeout(() => {
                this.toasters = this.toasters.filter(x => x.id !== id);
                this.cdr.detectChanges();
            }, 400);
        }, 5000);
        this.timers.push(dt);
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
                message: `Broadcasting to BNB Smart Chain…`,
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
                title: "Contract Approved ✓",
                message: `Loan smart contract executed successfully`,
            },
            {
                delay: 4800,
                type: "success",
                title: "Funds Disbursed 🎉",
                message: `₹${this.loan.amount.toLocaleString("en-IN")} transferred to ${bank?.bank ?? "your bank"} ${bank?.displayNumber ?? ""}`,
            },
        ];

        msgs.forEach(({ delay, type, title, message }) => {
            const t = setTimeout(() => {
                const id = ++this.toastCounter;
                this.toasters.push({ id, type, title, message, visible: true });
                this.cdr.detectChanges();
                // auto-dismiss after 4s
                const dt = setTimeout(() => {
                    const toast = this.toasters.find(x => x.id === id);
                    if (toast) toast.visible = false;
                    this.cdr.detectChanges();
                    // remove from array after slide-out animation
                    setTimeout(() => {
                        this.toasters = this.toasters.filter(x => x.id !== id);
                        this.cdr.detectChanges();
                    }, 400);
                }, 4000);
                this.timers.push(dt);
            }, delay);
            this.timers.push(t);
        });
    }

    dismissToast(id: number): void {
        const t = this.toasters.find(x => x.id === id);
        if (t) t.visible = false;
        this.cdr.detectChanges();
        setTimeout(() => {
            this.toasters = this.toasters.filter(x => x.id !== id);
            this.cdr.detectChanges();
        }, 400);
    }

    formatAddress(addr: string): string {
        return addr.slice(0, 6) + "…" + addr.slice(-4);
    }
}
