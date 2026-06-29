import { Injectable } from '@angular/core';
import { Subject, Observable } from 'rxjs';

export interface ChatMessage {
  type: 'message' | 'typing' | 'error';
  content: string;
  timestamp: Date;
  from: 'user' | 'ai';
}

@Injectable({ providedIn: 'root' })
export class WebsocketService {
  private socket!: WebSocket;
  private messageSubject = new Subject<ChatMessage>();

  messages$: Observable<ChatMessage> = this.messageSubject.asObservable();

  connect(url: string): void {
    this.socket = new WebSocket(url);

    this.socket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      this.messageSubject.next({
        type: data.type,
        content: data.content,
        timestamp: new Date(),
        from: 'ai',
      });
    };

    this.socket.onerror = () => {
      this.messageSubject.next({
        type: 'error',
        content: 'Error de conexión con el servidor.',
        timestamp: new Date(),
        from: 'ai',
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
