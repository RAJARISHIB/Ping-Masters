import { Component, OnInit } from "@angular/core";
import { ActivatedRoute, Router } from "@angular/router";
import { SharedModule } from "../../../app.module";
import { FormsModule } from "@angular/forms";
import { ApiService } from "../../../services/api.service";

interface Installment {
    number: number;
    amount: string;
    date: string;
    status: "paid" | "upcoming" | "overdue";
}

interface LoanData {
    id: string;
    title: string;
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
    loan: LoanData | null = null;
    isEditingTitle = false;
    editedTitle = "";
    isPayingInstallment = false;
    loading = false;
    razorpayAvailable = false;
    explainabilityReasons: string[] = [];
    recommendedTopupToken = 0;
    safetyColor = "";

    get priceChange(): number {
        if (!this.loan) return 0;
        return ((this.loan.currentPrice - this.loan.entryPrice) / this.loan.entryPrice) * 100;
    }

    get progressPercent(): number {
        if (!this.loan) return 0;
        return Math.round((this.loan.paidInstallments / this.loan.totalInstallments) * 100);
    }

    get marginFromLiquidation(): number {
        if (!this.loan) return 0;
        return ((this.loan.currentPrice - this.loan.liquidationPrice) / this.loan.currentPrice) * 100;
    }

    constructor(private route: ActivatedRoute, private router: Router, private api: ApiService) {}

    ngOnInit(): void {
        const id = this.route.snapshot.paramMap.get("id") || "";
        if (!id) return;
        this.loadRazorpayStatus();
        this.loadLoan(id);
    }

    private loadRazorpayStatus(): void {
        this.api.getRazorpayStatus().subscribe({
            next: (res) => {
                this.razorpayAvailable = !!res.available;
            },
            error: () => {
                this.razorpayAvailable = false;
            },
        });
    }

    private loadLoan(id: string): void {
        this.loading = true;

        this.api.getBnplSafetyMeter(id).subscribe({
            next: (safetyRes) => {
                this.safetyColor = String(safetyRes.safety_color || "");
                this.api.getBnplProof(id).subscribe({
                    next: (proofRes) => {
                        this.api.getBnplExplainability(id).subscribe({
                            next: (expRes) => {
                                this.explainabilityReasons = expRes.reasons || [];
                                this.api.getBnplDepositRecommendation(id, true).subscribe({
                                    next: (depositRes) => {
                                        this.recommendedTopupToken = Number(depositRes.topup_token || 0);
                                        this.loan = this.mapToLoanData(id, safetyRes, proofRes);
                                        this.editedTitle = this.loan.title;
                                        this.loading = false;
                                    },
                                    error: () => {
                                        this.loan = this.mapToLoanData(id, safetyRes, proofRes);
                                        this.editedTitle = this.loan.title;
                                        this.loading = false;
                                    },
                                });
                            },
                            error: () => {
                                this.loan = this.mapToLoanData(id, safetyRes, proofRes);
                                this.editedTitle = this.loan.title;
                                this.loading = false;
                            },
                        });
                    },
                    error: () => {
                        this.loan = null;
                        this.loading = false;
                    },
                });
            },
            error: () => {
                this.loan = null;
                this.loading = false;
            },
        });
    }

    private mapToLoanData(id: string, safetyRes: Record<string, any>, proofRes: Record<string, any>): LoanData {
        const proofLoan = proofRes?.['loan'];
        const proofFinancial = proofRes?.['financial_summary'];
        const proofCollateral = proofRes?.['collateral'];
        const proofThresholds = proofRes?.['thresholds'];
        const proofTimeline = proofRes?.['timeline'];

        const principalMinor = Number(
            proofLoan?.['principal_minor']
            ?? proofFinancial?.['principal_minor']
            ?? 0
        );
        const outstandingMinor = Number(
            safetyRes?.['outstanding_minor']
            ?? proofFinancial?.['outstanding_minor']
            ?? principalMinor
        );
        const paidMinor = Math.max(0, principalMinor - outstandingMinor);
        const collateralUnits = Number(
            proofCollateral?.['deposited_units']
            ?? proofCollateral?.['locked_token']
            ?? 0
        );
        const collateralValueMinor = Number(safetyRes?.['collateral_value_minor'] ?? 0);
        const currentPrice = collateralUnits > 0 ? (collateralValueMinor / 100) / collateralUnits : 0;
        const liquidationPrice = Number(
            proofLoan?.['liquidation_price']
            ?? proofThresholds?.['liquidation_price']
            ?? 0
        );

        const installmentsRaw = Array.isArray(proofRes?.['installments'])
            ? proofRes['installments']
            : Array.isArray(proofTimeline?.['installments'])
                ? proofTimeline['installments']
                : [];

        const pastInstallments: Installment[] = installmentsRaw.map((installment: Record<string, any>, index: number) => {
            const statusRaw = String(installment['status'] || "upcoming").toLowerCase();
            const status: Installment["status"] = statusRaw.includes("paid")
                ? "paid"
                : statusRaw.includes("over") || statusRaw.includes("miss")
                    ? "overdue"
                    : "upcoming";
            const amountMinor = Number(installment['amount_minor'] || installment['installment_amount_minor'] || 0);
            return {
                number: Number(installment['number'] || installment['installment_number'] || index + 1),
                amount: `₹ ${(amountMinor / 100).toLocaleString("en-IN")}/-`,
                date: this.formatDate(installment['due_at'] || installment['date'] || installment['due_date']),
                status,
            };
        });

        const paidInstallments = pastInstallments.filter((item) => item.status === "paid").length;
        const nextInstallment = pastInstallments.find((item) => item.status !== "paid");
        const tenureDays = Number(proofLoan?.['tenure_days'] || 0);
        const startDateRaw = String(proofLoan?.['created_at'] || proofTimeline?.['created_at'] || "");
        const endDate = startDateRaw && tenureDays > 0
            ? new Date(new Date(startDateRaw).getTime() + tenureDays * 24 * 60 * 60 * 1000)
            : null;

        return {
            id,
            title: String(proofLoan?.['title'] || proofLoan?.['loan_name'] || `Loan ${id}`),
            collateralAsset: String(proofCollateral?.['asset_symbol'] || "BNB"),
            collateralAmount: Number(collateralUnits.toFixed(4)),
            entryPrice: Number(currentPrice.toFixed(2)),
            currentPrice: Number(currentPrice.toFixed(2)),
            liquidationPrice: Number(liquidationPrice.toFixed(2)),
            totalAmount: `₹ ${(principalMinor / 100).toLocaleString("en-IN")}/-`,
            paidAmount: `₹ ${(paidMinor / 100).toLocaleString("en-IN")}/-`,
            remainingAmount: `₹ ${(outstandingMinor / 100).toLocaleString("en-IN")}/-`,
            dueDate: endDate ? this.formatDate(endDate.toISOString()) : "—",
            installmentAmount: `₹ ${(Number(proofLoan?.['installment_amount_minor'] || 0) / 100).toLocaleString("en-IN")}/-`,
            totalInstallments: Number(proofLoan?.['installment_count'] ?? pastInstallments.length ?? 0),
            paidInstallments,
            nextInstallmentDate: nextInstallment ? nextInstallment.date : "—",
            lastInstallmentDate: pastInstallments.length ? pastInstallments[pastInstallments.length - 1].date : "—",
            pastInstallments,
            nextReminderDate: nextInstallment ? nextInstallment.date : "—",
            notificationModes: Array.isArray(proofLoan?.['notification_channels']) ? proofLoan['notification_channels'] : [],
        };
    }

    private formatDate(input?: string): string {
        if (!input) return "—";
        const d = new Date(input);
        if (Number.isNaN(d.getTime())) return "—";
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

    // ── Razorpay SDK payment ───────────────────────────────────
    get pendingInstallment(): { number: number; amount: string; date: string } | null {
        if (!this.loan) return null;
        const inst = this.loan.pastInstallments.find(
            (i) => i.status === "overdue" || i.status === "upcoming"
        );
        return inst ? { number: inst.number, amount: inst.amount, date: inst.date } : null;
    }

    openRazorpay(): void {
        if (!this.loan || this.isPayingInstallment) return;
        const pending = this.pendingInstallment;
        if (!pending) return;

        // Parse the INR amount string "₹ 12,500/-" → 1250000 paise
        const rawVal = parseFloat(pending.amount.replace(/[₹,\s/\-]/g, ""));
        const amountPaise = ApiService.toPaise(rawVal);

        this.isPayingInstallment = true;

        // Step 1: create autopay mandate via backend → get payment metadata
        this.api
            .createAutopayMandate({
                user_id: sessionStorage.getItem("user_id") || "user_001",
                loan_id: this.loan!.id,
                amount_minor: amountPaise,
                currency: "INR",
            })
            .subscribe({
                next: (_mandateRes) => {
                    // Step 2: open Razorpay checkout SDK
                    this.api.getRazorpayStatus().subscribe({
                        next: (statusRes) => {
                            if (!statusRes.available) {
                                this.isPayingInstallment = false;
                                this.razorpayAvailable = false;
                                return;
                            }
                            this.api
                                .openRazorpayCheckout(
                                    amountPaise,
                                    `Installment #${pending.number} — ${this.loan?.title}`,
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
                },
                error: (_err) => {
                    // Backend unavailable – open checkout directly with test key
                    this.api
                        .openRazorpayCheckout(
                            amountPaise,
                            `Installment #${pending.number} — ${this.loan?.title}`,
                        )
                        .then((paymentRes) => {
                            this.isPayingInstallment = false;
                            this.markInstallmentPaid(paymentRes.razorpay_payment_id);
                        })
                        .catch(() => {
                            this.isPayingInstallment = false;
                        });
                },
            });
    }

    private markInstallmentPaid(paymentId: string): void {
        if (!this.loan) return;
        const inst = this.loan.pastInstallments.find(
            (i) => i.status === "overdue" || i.status === "upcoming"
        );
        if (inst) {
            inst.status = "paid";
            this.loan.paidInstallments++;
            const instAmt = parseFloat(inst.amount.replace(/[₹,\s/\-]/g, ""));
            const remaining = parseFloat(this.loan.remainingAmount.replace(/[₹,\s/\-]/g, ""));
            const paid = parseFloat(this.loan.paidAmount.replace(/[₹,\s/\-]/g, ""));
            this.loan.remainingAmount = `₹ ${(remaining - instAmt).toLocaleString("en-IN")}/-`;
            this.loan.paidAmount = `₹ ${(paid + instAmt).toLocaleString("en-IN")}/-`;
            const next = this.loan.pastInstallments.find((i) => i.status === "upcoming");
            this.loan.nextInstallmentDate = next ? next.date : "—";
        }
        console.log(`Payment confirmed: ${paymentId}`);
    }
}
