import { Component, EventEmitter, Input, Output } from "@angular/core";
import { gsap } from "gsap";

export type WalletAddress = { name: string; wallet_id: string };

@Component({
    selector: "app-wallet-item",
    standalone: true,
    templateUrl: "./wallet-item.html",
    styleUrls: ["./wallet-item.scss"]
})
export class WalletItem {
    @Input() wallet: WalletAddress = { name: "Wallet", wallet_id: "Wallet - Address" };
    @Output() deleteWallet = new EventEmitter<void>();
    copied: boolean = false;

    copy(button?: HTMLElement | null): void {
        navigator.clipboard.writeText(this.wallet.wallet_id).then(() => {
            this.copied = true;
            if (button) {
                gsap.fromTo(
                    button,
                    { scale: 0.88 },
                    { scale: 1, duration: 0.25, ease: "back.out(2)" }
                );
            }
            setTimeout(() => { this.copied = false; }, 2000);
        });
    }
}
