import { Component, Input } from "@angular/core";
import { gsap } from "gsap";

@Component({
    selector: "app-wallet-item",
    standalone: true,
    templateUrl: "./wallet-item.html",
    styleUrls: ["./wallet-item.scss"]
})
export class WalletItem {
    @Input() address: string = "Wallet - Address";
    copied: boolean = false;

    copy(): void {
        navigator.clipboard.writeText(this.address).then(() => {
            this.copied = true;
            gsap.fromTo(".copy-btn",
                { scale: 0.88 },
                { scale: 1, duration: 0.25, ease: "back.out(2)" }
            );
            setTimeout(() => { this.copied = false; }, 2000);
        });
    }
}
