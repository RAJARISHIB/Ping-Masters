import { Injectable } from '@angular/core';
import { Subject, Observable } from 'rxjs';
import { filter, map } from 'rxjs/operators';

// Define a structure for your events
export interface BusEvent {
  key: string;
  data?: any;
}

@Injectable({
  providedIn: 'root'
})
export class EventBusService {
  private eventSubject = new Subject<BusEvent>();

  // Push an event into the bus
  emit(event: BusEvent) {
    this.eventSubject.next(event);
  }

  // Listen for specific events by key
  on(key: string): Observable<any> {
    return this.eventSubject.asObservable().pipe(
      filter(event => event.key === key),
      map(event => event.data)
    );
  }
}
