import { Injectable } from '@angular/core';
import { Subject, Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface ChatMessage {
  type: 'message' | 'typing' | 'error' | 'system' | 'history';
  content: string;
  username: string;
  from: 'user' | 'ai' | 'system';
  timestamp: Date;
  users?: string[];
  messages?: ChatMessage[];
}

@Injectable({ providedIn: 'root' })
export class WebsocketService {
  private socket!: WebSocket;
  private messageSubject = new Subject<ChatMessage>();

  messages$: Observable<ChatMessage> = this.messageSubject.asObservable();

  connect(roomId: string, username: string): void {
    this.socket = new WebSocket(`${environment.wsUrl}/ws/${roomId}/${username}`);

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
            timestamp: new Date(m.timestamp),
          })),
        });
      } else {
        this.messageSubject.next({ ...data, timestamp: new Date() });
      }
    };

    this.socket.onerror = () => {
      this.messageSubject.next({
        type: 'error',
        content: 'Error de conexión con el servidor.',
        username: 'Sistema',
        from: 'system',
        timestamp: new Date(),
      });
    };
  }

  sendMessage(content: string): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({ content }));
    }
  }

  disconnect(): void {
    this.socket?.close();
  }
}
