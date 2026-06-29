import { Component, OnInit, OnDestroy, ViewChild, ElementRef, AfterViewChecked } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { WebsocketService, ChatMessage, ConnectionState } from '../../services/websocket';
import { UserService } from '../../services/user.service';
import { Subscription } from 'rxjs';

@Component({
  selector: 'app-chat',
  imports: [CommonModule, FormsModule],
  templateUrl: './chat.html',
  styleUrl: './chat.scss',
})
export class Chat implements OnInit, OnDestroy, AfterViewChecked {
  @ViewChild('messagesContainer') messagesContainer!: ElementRef;

  messages: ChatMessage[] = [];
  inputText = '';
  isTyping = false;
  roomId = '';
  usersInRoom: string[] = [];
  connectionState: ConnectionState = 'reconnecting';
  showUsers = false;
  copied = false;

  private subs: Subscription[] = [];
  private shouldScroll = false;

  get username(): string {
    return this.userService.username;
  }

  get isConnected(): boolean {
    return this.connectionState === 'connected';
  }

  get isFatalError(): boolean {
    return this.connectionState === 'fatal_error';
  }

  constructor(
    private ws: WebsocketService,
    private userService: UserService,
    private route: ActivatedRoute,
    private router: Router
  ) {}

  ngOnInit(): void {
    if (!this.userService.isLoggedIn()) {
      this.router.navigate(['/']);
      return;
    }

    this.roomId = this.route.snapshot.paramMap.get('id') || '';
    this.ws.connect(this.roomId, this.username);

    this.subs.push(
      this.ws.state$.subscribe((state) => (this.connectionState = state))
    );

    this.subs.push(
      this.ws.messages$.subscribe((msg) => {
        if (msg.type === 'history') {
          this.messages = msg.messages ?? [];
        } else if (msg.type === 'typing') {
          this.isTyping = true;
        } else {
          this.isTyping = false;
          this.messages.push(msg);
          if (msg.users) this.usersInRoom = msg.users;
        }
        this.shouldScroll = true;
      })
    );
  }

  ngAfterViewChecked(): void {
    if (this.shouldScroll) {
      this.scrollToBottom();
      this.shouldScroll = false;
    }
  }

  sendMessage(): void {
    const text = this.inputText.trim();
    if (!text || !this.isConnected) return;
    this.ws.sendMessage(text);
    this.inputText = '';
  }

  onKeyDown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.sendMessage();
    }
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

  toggleUsers(): void {
    this.showUsers = !this.showUsers;
  }

  userInitial(name: string): string {
    return name.charAt(0).toUpperCase();
  }

  goBack(): void {
    this.router.navigate(['/lobby']);
  }

  private scrollToBottom(): void {
    try {
      this.messagesContainer.nativeElement.scrollTop =
        this.messagesContainer.nativeElement.scrollHeight;
    } catch {}
  }

  ngOnDestroy(): void {
    this.subs.forEach((s) => s.unsubscribe());
    this.ws.disconnect();
  }

  formatTime(date: Date): string {
    return new Date(date).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
  }
}
