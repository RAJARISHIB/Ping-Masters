import { Injectable } from "@angular/core";
import currencyJson from "../asset/currency.json";

type CurrencyEntry = {
    key: string;
    symbol?: string;
    value?: string;
};

@Injectable({ providedIn: "root" })
export class CurrencySymbolService {
    private readonly symbolMap: Map<string, string>;
    private readonly symbolFallbacks: Record<string, string> = {
        USD: "$",
        EUR: "€",
        GBP: "£",
        JPY: "¥",
        KRW: "₩",
        RUB: "₽",
        INR: "₹",
    };

    constructor() {
        this.symbolMap = new Map<string, string>();
        const payload = currencyJson as { data?: CurrencyEntry[] };
        const entries = Array.isArray(payload.data) ? payload.data : [];
        entries.forEach((entry) => {
            const code = String(entry.key || "").trim().toUpperCase();
            if (!code) return;
            const normalized = this.normalizeSymbol(String(entry.symbol || "").trim(), code);
            if (normalized) {
                this.symbolMap.set(code, normalized);
            }
        });
    }

    resolveSymbol(currencyCode: string, fallbackCode: string = "USD"): string {
        const code = String(currencyCode || fallbackCode || "").trim().toUpperCase();
        if (!code) return "";
        const symbol = this.symbolMap.get(code);
        if (symbol) return symbol;
        return this.symbolFallbacks[code] || code;
    }

    private normalizeSymbol(rawSymbol: string, currencyCode: string): string {
        if (!rawSymbol) {
            return this.symbolFallbacks[currencyCode] || "";
        }
        if (currencyCode === "INR") return "₹";
        if (rawSymbol === "Rs" || rawSymbol === "Rs.") return "₹";
        return rawSymbol;
    }
}
