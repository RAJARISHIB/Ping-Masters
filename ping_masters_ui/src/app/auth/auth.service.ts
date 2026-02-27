import { Injectable, inject } from '@angular/core';
import { Auth } from '@angular/fire/auth';
import { Firestore } from '@angular/fire/firestore';
import {
  AdditionalUserInfo,
  GoogleAuthProvider,
  User,
  getAdditionalUserInfo,
  onAuthStateChanged,
  signInWithPopup,
  signOut
} from 'firebase/auth';
import { doc, getDoc, serverTimestamp, setDoc } from 'firebase/firestore';
import { Observable } from 'rxjs';
import { shareReplay } from 'rxjs/operators';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly auth = inject(Auth);
  private readonly firestore = inject(Firestore);

  readonly user$: Observable<User | null> = new Observable<User | null>((subscriber) =>
    onAuthStateChanged(this.auth, (user) => subscriber.next(user), (error) => subscriber.error(error))
  ).pipe(shareReplay({ bufferSize: 1, refCount: true }));

  async signInWithGoogle(): Promise<void> {
    const provider = new GoogleAuthProvider();
    provider.setCustomParameters({ prompt: 'select_account' });
    const userCredential = await signInWithPopup(this.auth, provider);

    const additionalUserInfo = getAdditionalUserInfo(userCredential);
    await this.ensureUserDocument(userCredential.user, additionalUserInfo);
  }

  async logout(): Promise<void> {
    await signOut(this.auth);
  }

  async needsGetStarted(uid: string): Promise<boolean> {
    const userRef = doc(this.firestore, 'user', uid);
    const snapshot = await getDoc(userRef);
    if (!snapshot.exists()) return true;

    const data = snapshot.data() as { wallet_address?: unknown } | undefined;
    const wallets = data?.wallet_address;
    return !Array.isArray(wallets) || wallets.length === 0;
  }

  async saveGetStartedDetails(
    uid: string,
    details: {
      wallet_address: Array<{ name: string; wallet_id: string }>;
      mobile_number: string | null;
      notification_channels: string[];
    }
  ): Promise<void> {
    const userRef = doc(this.firestore, 'user', uid);

    await setDoc(
      userRef,
      {
        wallet_address: details.wallet_address,
        mobile_number: details.mobile_number,
        notification_channels: details.notification_channels
      },
      { merge: true }
    );
  }

  private async ensureUserDocument(user: User, info: AdditionalUserInfo | null): Promise<void> {
    const userRef = doc(this.firestore, 'user', user.uid);
    const snapshot = await getDoc(userRef);

    const baseDoc = this.buildUserDoc(user, info);
    const now = serverTimestamp();

    if (!snapshot.exists()) {
      await setDoc(userRef, { ...baseDoc, createdAt: now, lastLoginAt: now });
      return;
    }

    await setDoc(userRef, { ...baseDoc, lastLoginAt: now }, { merge: true });
  }

  private buildUserDoc(user: User, info: AdditionalUserInfo | null) {
    const profile = (info?.profile ?? {}) as Record<string, unknown>;
    const providerUserId = this.pickString(profile['id']);

    const firstName = this.pickString(profile['given_name']);
    const lastName = this.pickString(profile['family_name']);
    const fullName = this.pickString(profile['name']) ?? user.displayName;

    return {
      localId: user.uid,
      providerId: info?.providerId ?? null,
      federatedId: providerUserId ? `https://accounts.google.com/${providerUserId}` : null,
      email: user.email ?? null,
      emailVerified: user.emailVerified,
      firstName: firstName ?? null,
      lastName: lastName ?? null,
      fullName: fullName ?? null,
      displayName: user.displayName ?? null,
      photoUrl: user.photoURL ?? null
    };
  }

  private pickString(value: unknown): string | null {
    if (typeof value !== 'string') return null;
    const trimmed = value.trim();
    return trimmed ? trimmed : null;
  }
}
