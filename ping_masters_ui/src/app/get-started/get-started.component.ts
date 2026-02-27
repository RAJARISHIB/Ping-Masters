import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormArray, FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { Router, RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { distinctUntilChanged, take } from 'rxjs/operators';
import type { User } from 'firebase/auth';
import { AuthService } from '../auth/auth.service';
import currencyJson from '../asset/currency.json';
import { UsersApiService } from '../api/users-api.service';

type WalletAddress = { name: string; wallet_id: string };
type CurrencyOption = { key: string; value: string; symbol?: string; emoji?: string };

@Component({
  selector: 'app-get-started',
  imports: [ReactiveFormsModule, RouterLink],
  templateUrl: './get-started.component.html',
  styleUrl: './get-started.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class GetStartedComponent {
  private readonly authService = inject(AuthService);
  private readonly router = inject(Router);
  private readonly fb = inject(FormBuilder);
  private readonly usersApiService = inject(UsersApiService);

  readonly user$ = this.authService.user$;

  readonly saving = signal(false);
  readonly error = signal<string | null>(null);

  private readonly currencies: CurrencyOption[] = (currencyJson as { data: CurrencyOption[] }).data;
  readonly currencyOpen = signal(false);
  readonly currencyQuery = signal('');
  readonly selectedCurrencyKey = signal('INR');
  readonly selectedCurrencyDisplay = computed(() => {
    const key = this.selectedCurrencyKey();
    const selected = this.currencies.find((currency) => currency.key === key);
    return selected ? this.formatCurrency(selected) : key;
  });

  readonly filteredCurrencies = computed(() => {
    const query = this.currencyQuery().trim().toLowerCase();
    const selectedDisplay = this.selectedCurrencyDisplay().trim().toLowerCase();
    const normalizedQuery = query === selectedDisplay ? '' : query;

    const list = !normalizedQuery
      ? this.currencies
      : this.currencies.filter((currency) => this.matchesCurrency(currency, normalizedQuery));

    return list;
  });

  readonly form = this.fb.group({
    wallet_address: this.fb.array([this.createWalletGroup()]),
    currency: this.fb.control('INR', { nonNullable: true, validators: [Validators.required] }),
    mobile_number: this.fb.control('', {
      validators: [Validators.pattern(/^\+?[0-9]{8,15}$/)]
    }),
    notifyEmail: this.fb.control(true, { nonNullable: true }),
    notifyWhatsapp: this.fb.control(false, { nonNullable: true })
  });

  constructor() {
    this.currencyQuery.set(this.selectedCurrencyDisplay());

    this.form.controls.notifyWhatsapp.valueChanges
      .pipe(takeUntilDestroyed())
      .subscribe((enabled) => this.updateMobileValidators(enabled));
    this.updateMobileValidators(this.form.controls.notifyWhatsapp.value);

    this.user$
      .pipe(
        distinctUntilChanged((a, b) => a?.uid === b?.uid),
        takeUntilDestroyed()
      )
      .subscribe((user) => void this.handleUser(user));
  }

  get wallets(): FormArray {
    return this.form.controls.wallet_address;
  }

  addWallet(): void {
    this.wallets.push(this.createWalletGroup());
  }

  removeWallet(index: number): void {
    if (this.wallets.length <= 1) return;
    this.wallets.removeAt(index);
  }

  onCurrencyFocus(event: FocusEvent): void {
    this.currencyOpen.set(true);
    const input = event.target as HTMLInputElement | null;
    input?.select();
  }

  onCurrencyInput(value: string): void {
    this.currencyQuery.set(value);
    this.currencyOpen.set(true);
  }

  onCurrencyFocusOut(event: FocusEvent): void {
    const currentTarget = event.currentTarget as HTMLElement;
    const nextTarget = event.relatedTarget as Node | null;

    if (nextTarget && currentTarget.contains(nextTarget)) return;

    this.currencyOpen.set(false);
    this.currencyQuery.set(this.selectedCurrencyDisplay());
  }

  selectCurrency(currency: CurrencyOption): void {
    this.selectedCurrencyKey.set(currency.key);
    this.form.controls.currency.setValue(currency.key);
    this.currencyQuery.set(this.selectedCurrencyDisplay());
    this.currencyOpen.set(false);
  }

  async submit(): Promise<void> {
    if (this.saving()) return;

    this.error.set(null);
    this.form.markAllAsTouched();

    if (this.form.invalid) return;

    this.saving.set(true);

    try {
      const user = await firstValueFrom(this.user$.pipe(take(1)));
      if (!user) {
        await this.router.navigateByUrl('/login');
        return;
      }

      const wallets = this.wallets.controls.map((group) => {
        const typed = group as ReturnType<GetStartedComponent['createWalletGroup']>;
        const name = typed.controls.name.value.trim();
        const walletId = typed.controls.wallet_id.value.trim();
        return { name, wallet_id: walletId } satisfies WalletAddress;
      });

      const currency = this.form.controls.currency.value;

      const notificationChannels: string[] = [];
      if (this.form.controls.notifyEmail.value) notificationChannels.push('email');
      if (this.form.controls.notifyWhatsapp.value) notificationChannels.push('whatsapp');

      const mobileRaw = this.form.controls.mobile_number.value ?? '';
      const mobileNumber = mobileRaw.trim() ? mobileRaw.trim() : null;

      await firstValueFrom(
        this.usersApiService.createFromFirebase({
          user_id: user.uid,
          wallet_address: wallets,
          notification_channels: notificationChannels
        })
      );

      await this.authService.saveGetStartedDetails(user.uid, {
        wallet_address: wallets,
        currency,
        mobile_number: mobileNumber,
        notification_channels: notificationChannels
      });

      await this.router.navigateByUrl('/login');
    } catch (error: unknown) {
      this.error.set(this.humanizeError(error));
    } finally {
      this.saving.set(false);
    }
  }

  private async handleUser(user: User | null): Promise<void> {
    if (!user) {
      await this.router.navigateByUrl('/login');
      return;
    }

    const needsGetStarted = await this.authService.needsGetStarted(user.uid);
    if (!needsGetStarted) {
      await this.router.navigateByUrl('/login');
    }
  }

  private createWalletGroup() {
    return this.fb.group({
      name: this.fb.control('', { nonNullable: true, validators: [Validators.required] }),
      wallet_id: this.fb.control('', { nonNullable: true, validators: [Validators.required] })
    });
  }

  private updateMobileValidators(whatsappEnabled: boolean): void {
    const mobile = this.form.controls.mobile_number;
    if (whatsappEnabled) {
      mobile.addValidators([Validators.required]);
    } else {
      mobile.removeValidators([Validators.required]);
    }
    mobile.updateValueAndValidity({ emitEvent: false });
  }

  private formatCurrency(currency: CurrencyOption): string {
    const symbol = (currency.symbol ?? '').trim();
    return symbol ? `${currency.key} — ${currency.value} (${symbol})` : `${currency.key} — ${currency.value}`;
  }

  private matchesCurrency(currency: CurrencyOption, query: string): boolean {
    const key = currency.key.toLowerCase();
    const name = currency.value.toLowerCase();
    const symbol = (currency.symbol ?? '').toLowerCase();
    return key.includes(query) || name.includes(query) || symbol.includes(query);
  }

  private humanizeError(error: unknown): string {
    if (error instanceof HttpErrorResponse) {
      return `Request failed (${error.status}${error.statusText ? ` ${error.statusText}` : ''}).`;
    }

    if (error instanceof Error && error.message) return error.message;
    return 'Failed to save. Please try again.';
  }
}
