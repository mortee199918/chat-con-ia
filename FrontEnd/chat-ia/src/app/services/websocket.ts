import { Injectable } from '@angular/core';
import { Subject, Observable, BehaviorSubject } from 'rxjs';
import { environment } from '../../environments/environment';

export interface ChatMessage {
  type: 'message' | 'typing' | 'error' | 'system' | 'history';
  content: string;
  username: string;
  from: 'user' | 'ai' | 'system';
  timestamp: Date;
  users?: string[];
  messages?: ChatMessage[];
  isHistory?: boolean;
}

export type ConnectionState = 'connected' | 'reconnecting' | 'disconnected' | 'fatal_error';

@Injectable({ providedIn: 'root' })
export class WebsocketService {
  private socket!: WebSocket;
  private messageSubject = new Subject<ChatMessage>();
  private stateSubject = new BehaviorSubject<ConnectionState>('disconnected');

  messages$: Observable<ChatMessage> = this.messageSubject.asObservable();
  state$: Observable<ConnectionState> = this.stateSubject.asObservable();

  private roomId = '';
  private username = '';
  private intentionalClose = false;
  private retryDelay = 1000;
  private readonly maxDelay = 10000;
  private retryTimer?: ReturnType<typeof setTimeout>;

  connect(roomId: string, username: string): void {
    this.roomId = roomId;
    this.username = username;
    this.intentionalClose = false;
    this.retryDelay = 1000;
    this.doConnect();
  }

  private doConnect(): void {
    this.stateSubject.next('reconnecting');
    this.socket = new WebSocket(`${environment.wsUrl}/ws/${this.roomId}/${this.username}`);

    this.socket.onopen = () => {
      this.stateSubject.next('connected');
      this.retryDelay = 1000;
    };

    this.socket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'history') {
        this.messageSubject.next({
          type: 'history',
          content: '',
          username: '',
          from: 'system',
          timestamp: new Date(),
          messages: data.messages.map((m: ChatMessage) => ({
            ...m,
            timestamp: new Date(m.timestamp as unknown as string),
          })),
        });
      } else {
        this.messageSubject.next({ ...data, timestamp: new Date() });
      }
    };

    this.socket.onclose = (event) => {
      if (this.intentionalClose) return;

      // Errores fatales: no reconectar
      if (event.code === 4001 || event.code === 4004) {
        this.stateSubject.next('fatal_error');
        return;
      }

      this.stateSubject.next('reconnecting');
      this.retryTimer = setTimeout(() => this.doConnect(), this.retryDelay);
      this.retryDelay = Math.min(this.retryDelay * 2, this.maxDelay);
    };

    this.socket.onerror = () => {
      // onclose siempre se dispara después de onerror
    };
  }

  sendMessage(content: string): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({ content }));
    }
  }

  disconnect(): void {
    this.intentionalClose = true;
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.socket?.close();
    this.stateSubject.next('disconnected');
  }
}
