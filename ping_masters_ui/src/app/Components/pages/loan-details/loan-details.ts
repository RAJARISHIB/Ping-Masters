import { Component, OnInit } from "@angular/core";
import { ActivatedRoute, Router } from "@angular/router";
import { SharedModule } from "../../../app.module";
import { FormsModule } from "@angular/forms";
import { firstValueFrom, of } from "rxjs";
import { catchError, timeout } from "rxjs/operators";
import { ApiService } from "../../../services/api.service";
import { CurrencySymbolService } from "../../../services/currency-symbol.service";

interface Installment {
    number: number;
    amount: string;
    date: string;
    status: "paid" | "upcoming" | "overdue";
}

interface LoanData {
    id: string;
    title: string;
    currencyCode: string;
    currencySymbol: string;
    collateralAsset: string;
    collateralAmount: number;
    entryPrice: number;
    currentPrice: number;
    liquidationPrice: number;
    totalAmount: string;
    paidAmount: string;
    remainingAmount: string;
    dueDate: string;
    installmentAmount: string;
    totalInstallments: number;
    paidInstallments: number;
    nextInstallmentDate: string;
    lastInstallmentDate: string;
    pastInstallments: Installment[];
    nextReminderDate: string;
    notificationModes: string[];
}

@Component({
    selector: "app-loan-details",
    templateUrl: "./loan-details.html",
    styleUrls: ["./loan-details.scss"],
    imports: [SharedModule, FormsModule],
})
export class LoanDetails implements OnInit {
    private attemptedRedirectFromMissingLoan = false;

    loan: LoanData | null = null;
    isEditingTitle = false;
    editedTitle = "";
    isPayingInstallment = false;
    loading = false;
    razorpayAvailable = false;
    razorpayCheckoutKey = "";
    explainabilityReasons: string[] = [];
    recommendedTopupToken = 0;
    safetyColor = "";
    userId = "";
    userCurrencyCode = "USD";
    userCurrencySymbol = "$";

    get priceChange(): number {
        if (!this.loan || !this.loan.entryPrice) return 0;
        return ((this.loan.currentPrice - this.loan.entryPrice) / this.loan.entryPrice) * 100;
    }

    get progressPercent(): number {
        if (!this.loan || !this.loan.totalInstallments) return 0;
        return Math.round((this.loan.paidInstallments / this.loan.totalInstallments) * 100);
    }

    get marginFromLiquidation(): number {
        if (!this.loan || !this.loan.currentPrice) return 0;
        return ((this.loan.currentPrice - this.loan.liquidationPrice) / this.loan.currentPrice) * 100;
    }

    constructor(
        private route: ActivatedRoute,
        private router: Router,
        private api: ApiService,
        private currencySymbols: CurrencySymbolService,
    ) {}

    ngOnInit(): void {
        this.userId = sessionStorage.getItem("user_id") || "user_001";
        this.loadUserCurrencyContext();
        const id = this.route.snapshot.paramMap.get("id") || "";
        if (!id) return;
        void this.loadLoan(id);
    }

    private loadUserCurrencyContext(): void {
        if (!this.userId) return;
        this.api.getUser(this.userId).pipe(catchError(() => of(null))).subscribe((user) => {
            const code = String(user?.currency_code || this.userCurrencyCode || "USD").toUpperCase();
            this.userCurrencyCode = code;
            this.userCurrencySymbol = this.currencySymbols.resolveSymbol(code);
            if (this.loan) {
                const resolvedCode = this.loan.currencyCode || this.userCurrencyCode;
                this.loan.currencyCode = resolvedCode;
                this.loan.currencySymbol = this.currencySymbols.resolveSymbol(resolvedCode, this.userCurrencyCode);
            }
        });
    }

    private async loadLoan(id: string): Promise<void> {
        this.loading = true;
        let loanMeta: Record<string, any> | null = null;
        let safetyPayload: Record<string, any> = {};
        let proofPayload: Record<string, any> = {};
        try {
            const loanList = await firstValueFrom(
                this.api.getBnplLoans(this.userId, 200).pipe(
                    timeout(30000),
                    catchError(() => of({ loans: [] as Array<Record<string, any>> })),
                ),
            );
            const loanRows = Array.isArray((loanList as Record<string, any>)["loans"])
                ? ((loanList as Record<string, any>)["loans"] as Array<Record<string, any>>)
                : [];
            loanMeta = loanRows.find((row) => {
                const rowId = String(row["loan_id"] || row["id"] || "").trim();
                return rowId === id;
            }) || null;

            if (loanMeta) {
                this.loan = this.mapToLoanData(id, {}, {}, loanMeta);
                this.editedTitle = this.loan.title;
            }

            const [safetyResult, proofResult] = await Promise.allSettled([
                firstValueFrom(this.api.getBnplSafetyMeter(id).pipe(timeout(60000))),
                firstValueFrom(this.api.getBnplProof(id).pipe(timeout(60000))),
            ]);

            if (safetyResult.status === "fulfilled" && safetyResult.value) {
                safetyPayload = safetyResult.value as Record<string, any>;
            }
            if (proofResult.status === "fulfilled" && proofResult.value) {
                proofPayload = proofResult.value as Record<string, any>;
            }

            if (loanMeta || Object.keys(safetyPayload).length > 0 || Object.keys(proofPayload).length > 0) {
                this.loan = this.mapToLoanData(id, safetyPayload, proofPayload, loanMeta);
                this.editedTitle = this.loan.title;
                this.safetyColor = String(safetyPayload["safety_color"] || this.safetyColor || "");
                this.attemptedRedirectFromMissingLoan = false;
                this.loadLoanOptionalPanels(id);
                return;
            }

            this.loan = null;
            this.razorpayAvailable = false;
            this.razorpayCheckoutKey = "";
            this.explainabilityReasons = [];
            this.recommendedTopupToken = 0;
            this.safetyColor = "";
            this.redirectToExistingLoanIfAny(id);
        } catch {
            this.loan = null;
            this.razorpayAvailable = false;
            this.razorpayCheckoutKey = "";
            this.explainabilityReasons = [];
            this.recommendedTopupToken = 0;
            this.safetyColor = "";
            this.redirectToExistingLoanIfAny(id);
        } finally {
            this.loading = false;
        }
    }

    private loadLoanOptionalPanels(loanId: string): void {
        this.api
            .getBnplExplainability(loanId)
            .pipe(timeout(20000), catchError(() => of({ reasons: [] })))
            .subscribe((explainability) => {
                this.explainabilityReasons = Array.isArray((explainability as Record<string, any>)["reasons"])
                    ? ((explainability as Record<string, any>)["reasons"] as string[])
                    : [];
            });

        this.api
            .getBnplDepositRecommendation(loanId, true)
            .pipe(timeout(20000), catchError(() => of(null)))
            .subscribe((deposit) => {
                const depositRecord = (deposit as Record<string, any> | null) || null;
                this.recommendedTopupToken = Number((depositRecord ? depositRecord["topup_token"] : 0) || 0);
            });

        this.api
            .getRazorpayStatus()
            .pipe(timeout(20000), catchError(() => of({ available: false, checkout_key_id: "" })))
            .subscribe((razorpay) => {
                this.razorpayAvailable = !!(razorpay as Record<string, any>)["available"];
                this.razorpayCheckoutKey = String((razorpay as Record<string, any>)["checkout_key_id"] || "").trim();
            });
    }

    private redirectToExistingLoanIfAny(currentLoanId: string): void {
        if (this.attemptedRedirectFromMissingLoan || !this.userId) return;
        this.attemptedRedirectFromMissingLoan = true;
        this.api
            .getBnplLoans(this.userId, 50)
            .pipe(catchError(() => of({ loans: [] as Array<Record<string, any>> })))
            .subscribe((response) => {
                const rows = Array.isArray(response?.loans) ? response.loans : [];
                const candidate = rows.find((row) => {
                    const loanId = String(row["loan_id"] || row["id"] || "").trim();
                    return !!loanId && loanId !== currentLoanId;
                });
                const fallbackLoanId = String(candidate?.["loan_id"] || candidate?.["id"] || "").trim();
                if (fallbackLoanId) {
                    void this.router.navigate(["/loan-details", fallbackLoanId], { replaceUrl: true });
                }
            });
    }

    private mapToLoanData(
        id: string,
        safetyRes: Record<string, any>,
        proofRes: Record<string, any>,
        loanMeta: Record<string, any> | null,
    ): LoanData {
        const proofLoan = proofRes["loan"] || loanMeta || {};
        const proofFinancial = proofRes["financial_summary"] || {};
        const proofCollateral = proofRes["collateral"] || {};
        const proofThresholds = proofRes["thresholds"] || {};
        const proofTimeline = proofRes["timeline"] || {};
        const collateralProofs = Array.isArray(proofRes["collateral_proofs"]) ? proofRes["collateral_proofs"] : [];
        const primaryCollateralProof = (collateralProofs[0] || {}) as Record<string, any>;

        const currencyCode = String(proofLoan["currency"] || this.userCurrencyCode || "USD").toUpperCase();
        const currencySymbol = this.currencySymbols.resolveSymbol(currencyCode, this.userCurrencyCode);

        const baseOutstandingMinor = Number(
            safetyRes["outstanding_minor"] ?? proofFinancial["outstanding_minor"] ?? proofLoan["outstanding_minor"] ?? 0,
        );
        const principalMinor = Number(
            proofLoan["principal_minor"]
            ?? proofFinancial["principal_minor"]
            ?? proofLoan["borrow_limit_minor"]
            ?? baseOutstandingMinor,
        );
        const outstandingMinor = Number(
            safetyRes["outstanding_minor"] ?? proofFinancial["outstanding_minor"] ?? proofLoan["outstanding_minor"] ?? principalMinor
        );
        const paidMinor = Math.max(0, principalMinor - outstandingMinor);

        const collateralValueMinor = Number(
            safetyRes["collateral_value_minor"]
            ?? proofCollateral["collateral_value_minor"]
            ?? primaryCollateralProof["collateral_value_minor"]
            ?? 0,
        );
        let collateralUnits = Number(
            proofCollateral["deposited_units"]
            ?? proofCollateral["locked_token"]
            ?? primaryCollateralProof["deposited_units"]
            ?? 0,
        );
        if (collateralUnits <= 0 && collateralValueMinor > 0) {
            collateralUnits = Number((collateralValueMinor / 100).toFixed(4));
        }
        const currentPrice = collateralUnits > 0 ? (collateralValueMinor / 100) / collateralUnits : 0;
        const liquidationPrice = Number(proofLoan["liquidation_price"] ?? proofThresholds["liquidation_price"] ?? 0);

        const installmentsRaw = Array.isArray(proofRes["installments"])
            ? proofRes["installments"]
            : Array.isArray(proofTimeline["installments"])
                ? proofTimeline["installments"]
                : [];

        const pastInstallments: Installment[] = installmentsRaw.map((installment: Record<string, any>, index: number) => {
            const statusRaw = String(installment["status"] || "upcoming").toLowerCase();
            const status: Installment["status"] =
                statusRaw.includes("paid")
                    ? "paid"
                    : statusRaw.includes("over") || statusRaw.includes("miss")
                        ? "overdue"
                        : "upcoming";
            const amountMinor = Number(installment["amount_minor"] || installment["installment_amount_minor"] || 0);
            return {
                number: Number(installment["number"] || installment["installment_number"] || index + 1),
                amount: this.formatMinorAmount(amountMinor, currencySymbol),
                date: this.formatDate(installment["due_at"] || installment["date"] || installment["due_date"]),
                status,
            };
        });

        const paidInstallments = pastInstallments.filter((item) => item.status === "paid").length;
        const nextInstallment = pastInstallments.find((item) => item.status !== "paid");
        const tenureDays = Number(proofLoan["tenure_days"] || 0);
        const startDateRaw = String(proofLoan["created_at"] || proofTimeline["created_at"] || "");
        const endDate = startDateRaw && tenureDays > 0
            ? new Date(new Date(startDateRaw).getTime() + tenureDays * 24 * 60 * 60 * 1000)
            : null;

        return {
            id,
            title: String(proofLoan["title"] || proofLoan["loan_name"] || `Loan ${id}`),
            currencyCode,
            currencySymbol,
            collateralAsset: String(proofCollateral["asset_symbol"] || "BNB"),
            collateralAmount: Number(collateralUnits.toFixed(4)),
            entryPrice: Number(currentPrice.toFixed(2)),
            currentPrice: Number(currentPrice.toFixed(2)),
            liquidationPrice: Number(liquidationPrice.toFixed(2)),
            totalAmount: this.formatMinorAmount(principalMinor, currencySymbol),
            paidAmount: this.formatMinorAmount(paidMinor, currencySymbol),
            remainingAmount: this.formatMinorAmount(outstandingMinor, currencySymbol),
            dueDate: endDate ? this.formatDate(endDate.toISOString()) : "-",
            installmentAmount: this.formatMinorAmount(Number(proofLoan["installment_amount_minor"] || 0), currencySymbol),
            totalInstallments: Number(proofLoan["installment_count"] ?? pastInstallments.length ?? 0),
            paidInstallments,
            nextInstallmentDate: nextInstallment ? nextInstallment.date : "-",
            lastInstallmentDate: pastInstallments.length ? pastInstallments[pastInstallments.length - 1].date : "-",
            pastInstallments,
            nextReminderDate: nextInstallment ? nextInstallment.date : "-",
            notificationModes: Array.isArray(proofLoan["notification_channels"]) ? proofLoan["notification_channels"] : [],
        };
    }

    private formatMinorAmount(amountMinor: number, symbol: string): string {
        return `${symbol} ${(Number(amountMinor || 0) / 100).toLocaleString("en-IN")}/-`;
    }

    private formatDate(input?: string): string {
        if (!input) return "-";
        const d = new Date(input);
        if (Number.isNaN(d.getTime())) return "-";
        return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
    }

    startEdit(): void {
        this.isEditingTitle = true;
    }

    saveTitle(): void {
        if (this.loan && this.editedTitle.trim()) {
            this.loan.title = this.editedTitle.trim();
        }
        this.isEditingTitle = false;
    }

    goBack(): void {
        this.router.navigate(["/board"]);
    }

    isNotificationActive(mode: string): boolean {
        return !!this.loan && this.loan.notificationModes.includes(mode);
    }

    toggleNotification(mode: string): void {
        if (!this.loan) return;
        const idx = this.loan.notificationModes.indexOf(mode);
        if (idx >= 0) {
            this.loan.notificationModes.splice(idx, 1);
        } else {
            this.loan.notificationModes.push(mode);
        }
    }

    get pendingInstallment(): { number: number; amount: string; date: string } | null {
        if (!this.loan) return null;
        const installment = this.loan.pastInstallments.find(
            (item) => item.status === "overdue" || item.status === "upcoming"
        );
        return installment ? { number: installment.number, amount: installment.amount, date: installment.date } : null;
    }

    openRazorpay(): void {
        if (!this.loan || this.isPayingInstallment) return;
        const pending = this.pendingInstallment;
        if (!pending) return;

        const amountValue = parseFloat(pending.amount.replace(/[^0-9.]/g, ""));
        if (!Number.isFinite(amountValue) || amountValue <= 0) return;

        const amountPaise = ApiService.toPaise(amountValue);
        this.isPayingInstallment = true;

        this.api
            .createAutopayMandate({
                user_id: sessionStorage.getItem("user_id") || "user_001",
                loan_id: this.loan.id,
                amount_minor: amountPaise,
                currency: this.loan.currencyCode || this.userCurrencyCode || "USD",
            })
            .subscribe({
                next: () => {
                    this.api
                        .openRazorpayCheckout(
                            amountPaise,
                            this.loan?.currencyCode || this.userCurrencyCode || "USD",
                            `Installment #${pending.number} - ${this.loan?.title}`,
                            undefined,
                            { keyId: this.razorpayCheckoutKey },
                        )
                        .then((paymentRes) => {
                            this.isPayingInstallment = false;
                            this.markInstallmentPaid(paymentRes.razorpay_payment_id);
                        })
                        .catch(() => {
                            this.isPayingInstallment = false;
                        });
                },
                error: () => {
                    this.isPayingInstallment = false;
                },
            });
    }

    private markInstallmentPaid(paymentId: string): void {
        if (!this.loan) return;

        const installment = this.loan.pastInstallments.find(
            (item) => item.status === "overdue" || item.status === "upcoming"
        );
        if (!installment) return;

        installment.status = "paid";
        this.loan.paidInstallments += 1;

        const installmentAmount = parseFloat(installment.amount.replace(/[^0-9.]/g, ""));
        const remaining = parseFloat(this.loan.remainingAmount.replace(/[^0-9.]/g, ""));
        const paid = parseFloat(this.loan.paidAmount.replace(/[^0-9.]/g, ""));
        this.loan.remainingAmount = `${this.loan.currencySymbol} ${(remaining - installmentAmount).toLocaleString("en-IN")}/-`;
        this.loan.paidAmount = `${this.loan.currencySymbol} ${(paid + installmentAmount).toLocaleString("en-IN")}/-`;

        const next = this.loan.pastInstallments.find((item) => item.status === "upcoming");
        this.loan.nextInstallmentDate = next ? next.date : "-";

        console.log(`Payment confirmed: ${paymentId}`);
    }
}
