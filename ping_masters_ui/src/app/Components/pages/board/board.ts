import { OnInit, Component } from "@angular/core";
import { EventBusService } from "../../../services/communication.service";
import { AuthService } from "../../../auth/auth.service";
import { Router } from "@angular/router";
import { SharedModule } from "../../../app.module";
import { ApiService } from "../../../services/api.service";

@Component({
    selector: "app-board",
    templateUrl: "./board.html",
    imports: [SharedModule],
    styleUrls: ["./board.scss"]
})
export class Board implements OnInit {
    user: any = null;
    loading = false;

    historyItems: Array<{ id: string; title: string; amount: string; status: string }> = [];

    wallets: string[] = [];

    constructor(
        private eventBus: EventBusService,
        private authService: AuthService,
        private router: Router,
        private api: ApiService,
    ) {
        this.eventBus.on("board").subscribe((data) => {
            console.log("Received data on board>>", data);
        });
    }

    ngOnInit(): void {
        this.authService.user$.subscribe((user) => {
            if (!user) {
                this.router.navigate(["/login"]);
                return;
            }
            this.user = user;
            sessionStorage.setItem("user_id", user.uid);
            this.loadBoardData(user.uid);
        });
    }

    private loadBoardData(userId: string): void {
        this.loading = true;

        this.api.getUserWallets(userId).subscribe({
            next: (res) => {
                const ids = (res.wallet_address || []).map((entry) => entry.wallet_id).filter(Boolean);
                this.wallets = ids;
                if (!this.wallets.length) {
                    const connectedWallet = sessionStorage.getItem("connected_wallet");
                    this.wallets = connectedWallet ? [connectedWallet] : [];
                }
            },
            error: () => {
                const connectedWallet = sessionStorage.getItem("connected_wallet");
                this.wallets = connectedWallet ? [connectedWallet] : [];
            },
        });

        this.api.getBnplAuditEvents(12).subscribe({
            next: (res) => {
                const events = res.events || [];
                this.historyItems = events.map((event: Record<string, any>, index: number) => {
                    const loanId = String(event['loan_id'] || event['loanId'] || `loan-${index + 1}`);
                    const amountMinor = Number(event['amount_minor'] || event['amountMinor'] || 0);
                    const statusRaw = String(event['status'] || event['event_type'] || "pending").toLowerCase();
                    const status = statusRaw.includes("fail")
                        ? "Failed"
                        : statusRaw.includes("paid") || statusRaw.includes("success") || statusRaw.includes("complete")
                            ? "Completed"
                            : "Pending";

                    return {
                        id: loanId,
                        title: String(event['title'] || event['event_name'] || `Loan ${loanId}`),
                        amount: amountMinor > 0 ? `₹ ${(amountMinor / 100).toLocaleString("en-IN")}/-` : "₹ 0/-",
                        status,
                    };
                });
                this.loading = false;
            },
            error: () => {
                this.historyItems = [];
                this.loading = false;
            },
        });
    }

    goToLoan(id: string): void {
        this.router.navigate(["/loan-details", id]);
    }

    navigateToBorrow(): void {
        this.router.navigate(["/borrow"]);
    }
}