import { Injectable, inject } from '@angular/core';
import { Auth } from '@angular/fire/auth';
import { GoogleAuthProvider, User, onAuthStateChanged, signInWithPopup, signOut } from 'firebase/auth';
import { Observable } from 'rxjs';
import { shareReplay } from 'rxjs/operators';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly auth = inject(Auth);

  readonly user$: Observable<User | null> = new Observable<User | null>((subscriber) =>
    onAuthStateChanged(this.auth, (user) => subscriber.next(user), (error) => subscriber.error(error))
  ).pipe(shareReplay({ bufferSize: 1, refCount: true }));

  async signInWithGoogle(): Promise<void> {
    const provider = new GoogleAuthProvider();
    provider.setCustomParameters({ prompt: 'select_account' });
    await signInWithPopup(this.auth, provider);
  }

  async logout(): Promise<void> {
    await signOut(this.auth);
  }
}
