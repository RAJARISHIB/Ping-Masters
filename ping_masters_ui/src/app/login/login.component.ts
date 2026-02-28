import { AsyncPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router } from '@angular/router';
import type { User } from 'firebase/auth';
import { distinctUntilChanged, filter, map, switchMap } from 'rxjs/operators';
import { AuthService } from '../auth/auth.service';
import { EventBusService } from '../services/communication.service';

@Component({
  selector: 'app-login',
  imports: [AsyncPipe],
  templateUrl: './login.component.html',
  styleUrl: './login.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class LoginComponent {
  private readonly authService = inject(AuthService);
  private readonly router = inject(Router);
  readonly user$ = this.authService.user$;
  readonly working = signal(false);
  readonly error = signal<string | null>(null);

  constructor(
    private _eventbus: EventBusService
  ) {
    this.user$
      .pipe(
        filter((user): user is User => user !== null),
        map((user) => user.uid),
        distinctUntilChanged(),
        switchMap((uid) => this.authService.needsGetStarted(uid)),
        takeUntilDestroyed()
      )
      .subscribe((needsGetStarted) => {
        if (needsGetStarted) {
          void this.router.navigateByUrl('/get-started');
          return;
        }

        void this.router.navigateByUrl('/board').then(() => {
          this._eventbus.emit({ key: 'board', data: { message: 'Hello from LoginComponent' } });
        });
      });
  }

  async signInWithGoogle(): Promise<void> {
    await this.run(() => this.authService.signInWithGoogle());
  }

  async signOut(): Promise<void> {
    await this.run(() => this.authService.logout());
  }

  getInitials(name: string | null | undefined): string {
    const value = (name ?? '').trim();
    if (!value) return 'U';

    const parts = value.split(/\s+/).filter(Boolean);
    const first = parts[0]?.[0] ?? '';
    const last = parts.length > 1 ? parts[parts.length - 1]?.[0] ?? '' : '';
    const initials = `${first}${last}`.toUpperCase();
    return initials || 'U';
  }

  private async run(action: () => Promise<void>): Promise<void> {
    if (this.working()) return;

    this.error.set(null);
    this.working.set(true);

    try {
      await action();
    } catch (error: unknown) {
      this.error.set(this.humanizeError(error));
    } finally {
      this.working.set(false);
    }
  }

  private humanizeError(error: unknown): string {
    const code = this.getFirebaseErrorCode(error);
    switch (code) {
      case 'auth/popup-blocked':
        return 'Popup blocked. Allow popups for this site and try again.';
      case 'auth/popup-closed-by-user':
        return 'Sign-in was cancelled.';
      case 'auth/operation-not-allowed':
        return 'Google sign-in is not enabled for this Firebase project.';
      case 'auth/unauthorized-domain':
        return 'This domain is not authorized for Firebase Auth.';
      default:
        if (error instanceof Error && error.message) return error.message;
        return 'Something went wrong. Please try again.';
    }
  }

  private getFirebaseErrorCode(error: unknown): string | null {
    if (!error || typeof error !== 'object') return null;
    const code = (error as { code?: unknown }).code;
    return typeof code === 'string' ? code : null;
  }
}
