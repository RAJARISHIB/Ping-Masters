import { Routes } from '@angular/router';

export const routes: Routes = [
  {
    path: 'login',
    loadComponent: () => import('./login/login.component').then((m) => m.LoginComponent)
  },
  {
    path: 'get-started',
    loadComponent: () => import('./get-started/get-started.component').then((m) => m.GetStartedComponent)
  },
  {
    path: "board",
    loadComponent: ()=> import('./Components/pages/board/board').then(m=>m.Board)
  },
  {
    path: "loan-details/:id",
    loadComponent: ()=> import('./Components/pages/loan-details/loan-details').then(m=>m.LoanDetails)
  },
  {
    path: "transaction",
    loadComponent: ()=> import('./Components/pages/transaction/transaction').then(m=>m.Transaction)
  },
  {
    path: "borrow",
    loadComponent: ()=> import('./Components/pages/borrow/borrow').then(m=>m.Borrow)
  },
  { path: '', pathMatch: 'full', redirectTo: 'login' },
  { path: '**', redirectTo: 'login' },
];
