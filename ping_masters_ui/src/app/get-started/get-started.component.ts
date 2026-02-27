import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormArray, FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { distinctUntilChanged, take } from 'rxjs/operators';
import type { User } from 'firebase/auth';
import { AuthService } from '../auth/auth.service';

type WalletAddress = { name: string; wallet_id: string };

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

  readonly user$ = this.authService.user$;

  readonly saving = signal(false);
  readonly error = signal<string | null>(null);

  readonly form = this.fb.group({
    wallet_address: this.fb.array([this.createWalletGroup()]),
    mobile_number: this.fb.control('', {
      validators: [Validators.pattern(/^\+?[0-9]{8,15}$/)]
    }),
    notifyEmail: this.fb.control(true, { nonNullable: true }),
    notifyWhatsapp: this.fb.control(false, { nonNullable: true })
  });

  constructor() {
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

      const notificationChannels: string[] = [];
      if (this.form.controls.notifyEmail.value) notificationChannels.push('email');
      if (this.form.controls.notifyWhatsapp.value) notificationChannels.push('whatsapp');

      const mobileRaw = this.form.controls.mobile_number.value ?? '';
      const mobileNumber = mobileRaw.trim() ? mobileRaw.trim() : null;

      await this.authService.saveGetStartedDetails(user.uid, {
        wallet_address: wallets,
        mobile_number: mobileNumber,
        notification_channels: notificationChannels
      });

      await this.router.navigateByUrl('/login');
    } catch (error: unknown) {
      this.error.set(error instanceof Error ? error.message : 'Failed to save. Please try again.');
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
}
