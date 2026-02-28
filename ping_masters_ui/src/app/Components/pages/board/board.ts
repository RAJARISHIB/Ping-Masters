import { Component, DestroyRef, OnInit, computed, inject, signal } from "@angular/core";
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
type HistoryItemView = {
    id: string;
    loanId: string;
    title: string;
    amount: string;
    status: string;
    createdAtMs: number;
};

@Component({
    selector: "app-board",
    templateUrl: "./board.html",
    imports: [SharedModule],
    styleUrls: ["./board.scss"],
})
export class Board implements OnInit {
    private readonly destroyRef = inject(DestroyRef);
    private readonly historyPageSize = 6;

    readonly user = signal<User | null>(null);
    readonly loading = signal(false);
    readonly historyItems = signal<HistoryItemView[]>([]);
    readonly historyCurrentPage = signal(1);
    readonly historyTotalPages = computed(() => {
        const totalItems = this.historyItems().length;
        return Math.max(1, Math.ceil(totalItems / this.historyPageSize));
    });
    readonly pagedHistoryItems = computed(() => {
        const page = this.historyCurrentPage();
        const start = (page - 1) * this.historyPageSize;
        const end = start + this.historyPageSize;
        return this.historyItems().slice(start, end);
    });
    readonly canGoPreviousHistoryPage = computed(() => this.historyCurrentPage() > 1);
    readonly canGoNextHistoryPage = computed(() => this.historyCurrentPage() < this.historyTotalPages());
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
                this.loadUserLoanIdsAndHistory(userId);
            },
            error: () => {
                this.userCurrencyCode.set("USD");
                this.userCurrencySymbol.set(this.currencySymbols.resolveSymbol("USD"));
                this.loadUserLoanIdsAndHistory(userId);
            },
        });
    }

    private loadUserLoanIdsAndHistory(userId: string): void {
        this.api.getBnplLoans(userId, 200).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: (res) => {
                const rows = Array.isArray(res.loans) ? res.loans : [];
                const knownLoanIds = new Set<string>();
                rows.forEach((row) => {
                    const loanId = this.toTrimmedString(row["loan_id"]) || this.toTrimmedString(row["id"]);
                    if (this.isLikelyLoanId(loanId)) {
                        knownLoanIds.add(loanId);
                    }
                });
                this.loadHistory(userId, knownLoanIds);
            },
            error: () => {
                this.loadHistory(userId, new Set<string>());
            },
        });
    }

    private loadHistory(userId: string, knownLoanIds: Set<string>): void {
        this.api.getBnplAuditEvents(100).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: (res) => {
                const events = res.events || [];
                const sortedEvents = events
                    .map((event: Record<string, any>, index: number) => ({ event, index }))
                    .sort((left, right) => {
                        const leftTime = this.extractEventTimestamp(left.event);
                        const rightTime = this.extractEventTimestamp(right.event);
                        if (leftTime !== rightTime) return rightTime - leftTime;
                        return right.index - left.index;
                    })
                    .map((item) => item.event);
                const mapped = sortedEvents.map((event: Record<string, any>, index: number) => {
                    const payload = this.toRecord(event["payload"]);
                    const loanId = this.toTrimmedString(event["loan_id"])
                        || this.toTrimmedString(event["loanId"])
                        || this.toTrimmedString(payload["loan_id"])
                        || this.toTrimmedString(payload["loanId"]);
                    const actorUserId = this.toTrimmedString(event["actor"]) || this.toTrimmedString(payload["user_id"]);
                    const loanBelongsToUser = this.isLikelyLoanId(loanId) && knownLoanIds.has(loanId);
                    const actorBelongsToUser = actorUserId === userId;
                    const includeEvent = knownLoanIds.size > 0
                        ? (loanBelongsToUser || actorBelongsToUser)
                        : actorBelongsToUser;
                    if (!includeEvent) return null;
                    const eventType = this.toTrimmedString(event["event_type"])
                        || this.toTrimmedString(event["event_name"])
                        || "pending";
                    const amountMinor = this.extractAmountMinor(event, payload);
                    const statusRaw = String(event["status"] || payload["status"] || eventType).toLowerCase();
                    const status = statusRaw.includes("fail")
                        ? "Failed"
                        : statusRaw.includes("paid") || statusRaw.includes("success") || statusRaw.includes("complete")
                            ? "Completed"
                            : "Pending";
                    const currencyCode = String(
                        event["currency"] || payload["currency"] || payload["currency_code"] || this.userCurrencyCode() || "USD",
                    ).toUpperCase();
                    const symbol = this.currencySymbols.resolveSymbol(currencyCode, this.userCurrencyCode());
                    const createdAtMs = this.extractEventTimestamp(event);
                    const eventId = String(
                        event["event_id"]
                            || event["id"]
                            || payload["event_id"]
                            || `${loanId || "event"}-${createdAtMs}-${index}`,
                    );
                    const defaultTitle = loanId
                        ? `${this.humanizeEventType(eventType)} • ${loanId}`
                        : this.humanizeEventType(eventType);

                    return {
                        id: eventId,
                        loanId,
                        title: String(event["title"] || payload["title"] || defaultTitle),
                        amount: amountMinor > 0 ? `${symbol} ${(amountMinor / 100).toLocaleString("en-IN")}/-` : `${symbol} 0/-`,
                        status,
                        createdAtMs,
                    };
                }).filter((item): item is HistoryItemView => item !== null);
                this.historyItems.set(mapped);
                this.historyCurrentPage.set(1);
                this.loading.set(false);
            },
            error: () => {
                this.historyItems.set([]);
                this.historyCurrentPage.set(1);
                this.loading.set(false);
            },
        });
    }

    previousHistoryPage(): void {
        if (!this.canGoPreviousHistoryPage()) return;
        this.historyCurrentPage.set(this.historyCurrentPage() - 1);
    }

    nextHistoryPage(): void {
        if (!this.canGoNextHistoryPage()) return;
        this.historyCurrentPage.set(this.historyCurrentPage() + 1);
    }

    private extractEventTimestamp(event: Record<string, any>): number {
        const payload = this.toRecord(event["payload"]);
        const candidates = [
            event["created_at"],
            event["createdAt"],
            event["timestamp"],
            event["event_time"],
            event["updated_at"],
            payload["created_at"],
            payload["timestamp"],
        ];
        for (const value of candidates) {
            const millis = this.toTimestampMillis(value);
            if (millis > 0) return millis;
        }
        return 0;
    }

    private toTimestampMillis(value: unknown): number {
        if (!value) return 0;
        if (typeof value === "number" && Number.isFinite(value)) {
            return value > 10_000_000_000 ? value : value * 1000;
        }
        if (typeof value === "string") {
            const parsed = Date.parse(value);
            return Number.isNaN(parsed) ? 0 : parsed;
        }
        if (typeof value === "object") {
            const snapshot = value as { seconds?: unknown; _seconds?: unknown; nanoseconds?: unknown; _nanoseconds?: unknown };
            const secondsValue = snapshot.seconds ?? snapshot._seconds;
            const nanosValue = snapshot.nanoseconds ?? snapshot._nanoseconds ?? 0;
            const seconds = Number(secondsValue);
            const nanos = Number(nanosValue);
            if (Number.isFinite(seconds)) {
                return (seconds * 1000) + (Number.isFinite(nanos) ? Math.floor(nanos / 1_000_000) : 0);
            }
        }
        return 0;
    }

    goToLoan(loanId: string): void {
        const normalized = this.toTrimmedString(loanId);
        if (!normalized || !this.isLikelyLoanId(normalized)) {
            return;
        }
        this.router.navigate(["/loan-details", normalized]);
    }

    private toRecord(value: unknown): Record<string, any> {
        if (value && typeof value === "object" && !Array.isArray(value)) {
            return value as Record<string, any>;
        }
        return {};
    }

    private toTrimmedString(value: unknown): string {
        return String(value ?? "").trim();
    }

    private isLikelyLoanId(value: string): boolean {
        return value.startsWith("loan_") || value.startsWith("loan-");
    }

    private extractAmountMinor(event: Record<string, any>, payload: Record<string, any>): number {
        const candidates = [
            event["amount_minor"],
            event["amountMinor"],
            payload["amount_minor"],
            payload["amountMinor"],
            payload["missed_amount_minor"],
            payload["needed_minor"],
            payload["seized_minor"],
            payload["late_fee_minor"],
            payload["penalty_minor"],
            payload["outstanding_minor"],
        ];
        for (const candidate of candidates) {
            const amount = Number(candidate);
            if (Number.isFinite(amount) && amount > 0) {
                return amount;
            }
        }
        return 0;
    }

    private humanizeEventType(eventType: string): string {
        const normalized = this.toTrimmedString(eventType).toLowerCase();
        if (!normalized) return "Transaction";
        return normalized
            .split("_")
            .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
            .join(" ");
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
