import { Component, DestroyRef, OnInit, inject, signal } from "@angular/core";
import { takeUntilDestroyed } from "@angular/core/rxjs-interop";
import { EventBusService } from "../../../services/communication.service";
import { AuthService } from "../../../auth/auth.service";
import { Router } from "@angular/router";
import { SharedModule } from "../../../app.module";
import { ApiService } from "../../../services/api.service";
import { CurrencySymbolService } from "../../../services/currency-symbol.service";
import type { User } from "firebase/auth";
import { distinctUntilChanged } from "rxjs/operators";

type WalletAddress = { name: string; wallet_id: string };

@Component({
    selector: "app-board",
    templateUrl: "./board.html",
    imports: [SharedModule],
    styleUrls: ["./board.scss"],
})
export class Board implements OnInit {
    private readonly destroyRef = inject(DestroyRef);

    readonly user = signal<User | null>(null);
    readonly loading = signal(false);
    readonly historyItems = signal<Array<{ id: string; title: string; amount: string; status: string }>>([]);
    readonly wallets = signal<WalletAddress[]>([]);
    readonly userCurrencyCode = signal("USD");
    readonly userCurrencySymbol = signal("$");

    readonly walletEditorOpen = signal(false);
    readonly walletNameInput = signal("");
    readonly walletIdInput = signal("");
    readonly walletSaving = signal(false);
    readonly walletDirty = signal(false);
    readonly walletError = signal<string | null>(null);

    readonly working = signal(false);
    readonly error = signal<string | null>(null);

    constructor(
        private eventBus: EventBusService,
        private authService: AuthService,
        private router: Router,
        private api: ApiService,
        private currencySymbols: CurrencySymbolService,
    ) {
        this.eventBus
            .on("board")
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((data) => {
                console.log("Received data on board>>", data);
            });
    }

    ngOnInit(): void {
        this.authService.user$
            .pipe(
                distinctUntilChanged((a, b) => a?.uid === b?.uid),
                takeUntilDestroyed(this.destroyRef),
            )
            .subscribe((user) => {
                this.user.set(user);

                if (!user) {
                    this.loading.set(false);
                    this.historyItems.set([]);
                    this.wallets.set([]);
                    void this.router.navigate(["/login"]);
                    return;
                }

                sessionStorage.setItem("user_id", user.uid);
                this.loadBoardData(user.uid);
            });
    }

    private loadBoardData(userId: string): void {
        this.loading.set(true);
        this.userCurrencySymbol.set(this.currencySymbols.resolveSymbol(this.userCurrencyCode()));

        this.api.getUserWallets(userId).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: (res) => {
                const apiWallets = (res.wallet_address || []) as WalletAddress[];
                const wallets = apiWallets
                    .map((entry) => ({
                        name: String(entry?.name ?? "").trim() || "Wallet",
                        wallet_id: String(entry?.wallet_id ?? "").trim(),
                    }))
                    .filter((entry) => entry.wallet_id);
                const connectedWallet = sessionStorage.getItem("connected_wallet");
                const fallback = connectedWallet ? [{ name: "Connected wallet", wallet_id: connectedWallet }] : [];
                this.wallets.set(wallets.length ? wallets : fallback);
                this.walletDirty.set(false);
            },
            error: () => {
                const connectedWallet = sessionStorage.getItem("connected_wallet");
                this.wallets.set(connectedWallet ? [{ name: "Connected wallet", wallet_id: connectedWallet }] : []);
                this.walletDirty.set(false);
            },
        });

        this.api.getUser(userId).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: (profile) => {
                const code = String(profile?.currency_code || this.userCurrencyCode() || "USD").toUpperCase();
                this.userCurrencyCode.set(code);
                this.userCurrencySymbol.set(this.currencySymbols.resolveSymbol(code));
                this.loadHistory();
            },
            error: () => {
                this.userCurrencyCode.set("USD");
                this.userCurrencySymbol.set(this.currencySymbols.resolveSymbol("USD"));
                this.loadHistory();
            },
        });
    }

    private loadHistory(): void {
        this.api.getBnplAuditEvents(12).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: (res) => {
                const events = res.events || [];
                const mapped = events.map((event: Record<string, any>, index: number) => {
                    const loanId = String(event["loan_id"] || event["loanId"] || `loan-${index + 1}`);
                    const amountMinor = Number(event["amount_minor"] || event["amountMinor"] || 0);
                    const statusRaw = String(event["status"] || event["event_type"] || "pending").toLowerCase();
                    const status = statusRaw.includes("fail")
                        ? "Failed"
                        : statusRaw.includes("paid") || statusRaw.includes("success") || statusRaw.includes("complete")
                            ? "Completed"
                            : "Pending";
                    const currencyCode = String(event["currency"] || this.userCurrencyCode() || "USD").toUpperCase();
                    const symbol = this.currencySymbols.resolveSymbol(currencyCode, this.userCurrencyCode());

                    return {
                        id: loanId,
                        title: String(event["title"] || event["event_name"] || `Loan ${loanId}`),
                        amount: amountMinor > 0 ? `${symbol} ${(amountMinor / 100).toLocaleString("en-IN")}/-` : `${symbol} 0/-`,
                        status,
                    };
                });
                this.historyItems.set(mapped);
                this.loading.set(false);
            },
            error: () => {
                this.historyItems.set([]);
                this.loading.set(false);
            },
        });
    }

    goToLoan(id: string): void {
        this.router.navigate(["/loan-details", id]);
    }

    navigateToBorrow(): void {
        this.router.navigate(["/borrow"]);
    }

    toggleWalletEditor(): void {
        this.walletError.set(null);
        const nextOpen = !this.walletEditorOpen();
        this.walletEditorOpen.set(nextOpen);
        if (!nextOpen) {
            this.walletNameInput.set("");
            this.walletIdInput.set("");
        }
    }

    removeWallet(walletId: string): void {
        this.walletError.set(null);
        const before = this.wallets();
        const next = before.filter((entry) => entry.wallet_id !== walletId);
        if (next.length === before.length) return;
        this.wallets.set(next);
        this.walletDirty.set(true);
    }

    async submitWalletChanges(): Promise<void> {
        if (this.walletSaving()) return;
        this.walletError.set(null);

        const currentUser = this.user();
        if (!currentUser) {
            void this.router.navigate(["/login"]);
            return;
        }

        const name = this.walletNameInput().trim();
        const walletId = this.walletIdInput().trim();

        if (name || walletId) {
            if (!name || !walletId) {
                this.walletError.set("Wallet name and wallet address are required.");
                return;
            }

            const exists = this.wallets().some((wallet) => wallet.wallet_id.toLowerCase() === walletId.toLowerCase());
            if (exists) {
                this.walletError.set("That wallet address is already added.");
                return;
            }

            this.wallets.set([...this.wallets(), { name, wallet_id: walletId }]);
            this.walletNameInput.set("");
            this.walletIdInput.set("");
            this.walletDirty.set(true);
        }

        if (!this.walletDirty()) {
            this.walletEditorOpen.set(false);
            return;
        }

        this.walletSaving.set(true);
        try {
            await this.authService.saveWalletAddresses(currentUser.uid, this.wallets());
            this.walletDirty.set(false);
            this.walletEditorOpen.set(false);
        } catch (error: unknown) {
            this.walletError.set(error instanceof Error ? error.message : "Failed to save wallets. Please try again.");
        } finally {
            this.walletSaving.set(false);
        }
    }

    async signOut(): Promise<void> {
        await this.run(() => this.authService.logout());
    }

    private async run(action: () => Promise<void>): Promise<void> {
        if (this.working()) return;

        this.error.set(null);
        this.working.set(true);

        try {
            await action();
        } catch (error: unknown) {
            this.error.set(this.humanizeError(error));
        } finally {
            this.working.set(false);
        }
    }

    private humanizeError(error: unknown): string {
        const code = this.getFirebaseErrorCode(error);
        switch (code) {
            case "auth/popup-blocked":
                return "Popup blocked. Allow popups for this site and try again.";
            case "auth/popup-closed-by-user":
                return "Sign-in was cancelled.";
            case "auth/operation-not-allowed":
                return "Google sign-in is not enabled for this Firebase project.";
            case "auth/unauthorized-domain":
                return "This domain is not authorized for Firebase Auth.";
            default:
                if (error instanceof Error && error.message) return error.message;
                return "Something went wrong. Please try again.";
        }
    }

    private getFirebaseErrorCode(error: unknown): string | null {
        if (!error || typeof error !== "object") return null;
        const code = (error as { code?: unknown }).code;
        return typeof code === "string" ? code : null;
    }
}
