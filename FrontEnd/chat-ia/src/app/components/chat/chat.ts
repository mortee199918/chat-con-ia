import { Component, OnInit, OnDestroy, ViewChild, ElementRef, AfterViewChecked } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { WebsocketService, ChatMessage, ConnectionState } from '../../services/websocket';
import { UserService } from '../../services/user.service';
import { RoomService } from '../../services/room';
import { Subscription } from 'rxjs';

@Component({
  selector: 'app-chat',
  imports: [CommonModule, FormsModule],
  templateUrl: './chat.html',
  styleUrl: './chat.scss',
})
export class Chat implements OnInit, OnDestroy, AfterViewChecked {
  @ViewChild('messagesContainer') messagesContainer!: ElementRef<HTMLElement>;
  @ViewChild('inputField') inputField!: ElementRef<HTMLTextAreaElement>;

  messages: ChatMessage[] = [];
  inputText = '';
  isTyping = false;
  roomId = '';
  roomName = '';
  usersInRoom: string[] = [];
  connectionState: ConnectionState = 'reconnecting';
  showUsers = false;
  copied = false;

  private subs: Subscription[] = [];
  private shouldScroll = false;
  private forceScroll = false;
  private unreadCount = 0;

  private readonly visibilityHandler = () => {
    if (!document.hidden && this.unreadCount > 0) {
      this.unreadCount = 0;
      document.title = this.roomName;
    }
  };

  get username(): string { return this.userService.username; }
  get isConnected(): boolean { return this.connectionState === 'connected'; }
  get isFatalError(): boolean { return this.connectionState === 'fatal_error'; }

  constructor(
    private ws: WebsocketService,
    private userService: UserService,
    private roomService: RoomService,
    private route: ActivatedRoute,
    private router: Router,
  ) {}

  ngOnInit(): void {
    if (!this.userService.isLoggedIn()) {
      this.router.navigate(['/']);
      return;
    }

    this.roomId = this.route.snapshot.paramMap.get('id') || '';

    const nameFromQuery = this.route.snapshot.queryParamMap.get('name');
    if (nameFromQuery) {
      this.roomName = nameFromQuery;
      document.title = this.roomName;
    } else {
      this.roomService.getRoom(this.roomId).subscribe({
        next: (room) => { this.roomName = room.name; document.title = this.roomName; },
        error: () => { this.roomName = `Sala ${this.roomId}`; document.title = this.roomName; },
      });
    }

    document.addEventListener('visibilitychange', this.visibilityHandler);
    this.ws.connect(this.roomId, this.username);

    this.subs.push(this.ws.state$.subscribe((state) => (this.connectionState = state)));

    this.subs.push(
      this.ws.messages$.subscribe((msg) => {
        if (msg.type === 'history') {
          this.messages = (msg.messages ?? []).map((m) => ({ ...m, isHistory: true }));
          this.forceScroll = true;
        } else if (msg.type === 'typing') {
          this.isTyping = true;
          this.shouldScroll = true;
        } else {
          this.isTyping = false;
          this.messages.push(msg);
          if (msg.users) this.usersInRoom = msg.users;

          if (document.hidden && msg.type === 'message' && msg.from !== 'system') {
            this.unreadCount++;
            document.title = `(${this.unreadCount}) ${this.roomName}`;
          }

          if (this.isOwnMessage(msg)) {
            this.forceScroll = true;
          } else {
            this.shouldScroll = true;
          }
        }
      }),
    );
  }

  ngAfterViewChecked(): void {
    if (this.forceScroll) {
      this.scrollToBottom();
      this.forceScroll = false;
      this.shouldScroll = false;
    } else if (this.shouldScroll && this.isNearBottom()) {
      this.scrollToBottom();
      this.shouldScroll = false;
    } else {
      this.shouldScroll = false;
    }
  }

  sendMessage(): void {
    const text = this.inputText.trim();
    if (!text || !this.isConnected) return;
    this.ws.sendMessage(text);
    this.inputText = '';
    if (this.inputField) {
      this.inputField.nativeElement.style.height = 'auto';
    }
  }

  onKeyDown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.sendMessage();
    }
  }

  autoResize(event: Event): void {
    const el = event.target as HTMLTextAreaElement;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 120) + 'px';
  }

  isOwnMessage(msg: ChatMessage): boolean {
    return msg.from === 'user' && msg.username === this.username;
  }

  shareRoom(): void {
    const url = `${window.location.origin}/room/${this.roomId}`;
    navigator.clipboard.writeText(url).then(() => {
      this.copied = true;
      setTimeout(() => (this.copied = false), 2000);
    });
  }

  toggleUsers(): void { this.showUsers = !this.showUsers; }

  userInitial(name: string): string { return name.charAt(0).toUpperCase(); }

  goBack(): void {
    document.title = 'Chat con IA';
    this.router.navigate(['/lobby']);
  }

  shouldShowDate(index: number): boolean {
    const msg = this.messages[index];
    if (msg.type === 'system' || !msg.timestamp) return false;
    let first = 0;
    while (first < this.messages.length && this.messages[first].type === 'system') first++;
    if (index === first) return true;
    let prev = index - 1;
    while (prev >= 0 && this.messages[prev].type === 'system') prev--;
    if (prev < 0) return true;
    const prevMsg = this.messages[prev];
    if (!prevMsg.timestamp) return true;
    return !this.isSameDay(new Date(msg.timestamp), new Date(prevMsg.timestamp));
  }

  formatDate(date: Date): string {
    const d = new Date(date);
    const today = new Date();
    const yesterday = new Date();
    yesterday.setDate(today.getDate() - 1);
    if (this.isSameDay(d, today)) return 'Hoy';
    if (this.isSameDay(d, yesterday)) return 'Ayer';
    return d.toLocaleDateString('es-ES', { day: 'numeric', month: 'long' });
  }

  formatTime(date: Date): string {
    return new Date(date).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
  }

  private isSameDay(a: Date, b: Date): boolean {
    return a.getFullYear() === b.getFullYear() &&
           a.getMonth() === b.getMonth() &&
           a.getDate() === b.getDate();
  }

  private isNearBottom(): boolean {
    const el = this.messagesContainer?.nativeElement;
    if (!el) return true;
    return el.scrollHeight - el.scrollTop - el.clientHeight < 150;
  }

  private scrollToBottom(): void {
    try {
      this.messagesContainer.nativeElement.scrollTop =
        this.messagesContainer.nativeElement.scrollHeight;
    } catch {}
  }

  ngOnDestroy(): void {
    document.removeEventListener('visibilitychange', this.visibilityHandler);
    document.title = 'Chat con IA';
    this.subs.forEach((s) => s.unsubscribe());
    this.ws.disconnect();
  }
}
