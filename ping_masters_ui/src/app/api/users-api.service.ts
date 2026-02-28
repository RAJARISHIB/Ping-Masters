import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { environment } from '../../environments/environment';

export type FromFirebaseUserPayload = {
  user_id: string;
  wallet_address: Array<{ name: string; wallet_id: string }>;
  notification_channels: string[];
};

@Injectable({ providedIn: 'root' })
export class UsersApiService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = environment.apiUrl.replace(/\/+$/, '');

  createFromFirebase(payload: FromFirebaseUserPayload) {
    const allowedChannels = new Set(['email', 'whatsapp']);
    const body: FromFirebaseUserPayload = {
      user_id: payload.user_id,
      wallet_address: payload.wallet_address.map(({ name, wallet_id }) => ({ name, wallet_id })),
      notification_channels: Array.from(
        new Set(payload.notification_channels.filter((channel) => allowedChannels.has(channel)))
      )
    };

    return this.http.post(`${this.baseUrl}/users/from-firebase`, body);
  }
}
