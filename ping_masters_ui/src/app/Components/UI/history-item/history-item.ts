import { Component, Input, Output, EventEmitter } from "@angular/core";

@Component({
    selector: "app-history-item",
    standalone: true,
    templateUrl: "./history-item.html",
    styleUrls: ["./history-item.scss"]
})
export class HistoryItem {
    @Input() title: string = "Debt Title";
    @Input() amount: string = "1,000/-";
    @Input() status: string = "Pending";
    @Output() itemClicked = new EventEmitter<void>();
}
