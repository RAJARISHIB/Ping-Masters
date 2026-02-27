import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { NavBar } from './Components/UI/navbar/navbar';
import { HistoryItem } from './Components/UI/history-item/history-item';
import { WalletItem } from './Components/UI/wallet-item/wallet-item';

@NgModule({
  declarations: [],
  imports: [
    CommonModule,
    RouterModule,
    NavBar,
    HistoryItem,
    WalletItem,
  ],
  exports: [
    CommonModule,
    RouterModule,
    NavBar,
    HistoryItem,
    WalletItem,
  ]
})
export class SharedModule {}