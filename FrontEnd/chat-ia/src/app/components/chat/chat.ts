import { Component, OnInit, OnDestroy, ViewChild, ElementRef, AfterViewChecked } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { WebsocketService, ChatMessage } from '../../services/websocket';
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

  private sub!: Subscription;
  private shouldScroll = false;

  get username(): string {
    return this.userService.username;
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

    this.sub = this.ws.messages$.subscribe((msg) => {
      if (msg.type === 'typing') {
        this.isTyping = true;
      } else {
        this.isTyping = false;
        this.messages.push(msg);
        if (msg.users) this.usersInRoom = msg.users;
      }
      this.shouldScroll = true;
    });
  }

  ngAfterViewChecked(): void {
    if (this.shouldScroll) {
      this.scrollToBottom();
      this.shouldScroll = false;
    }
  }

  sendMessage(): void {
    const text = this.inputText.trim();
    if (!text) return;
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

  copyRoomCode(): void {
    navigator.clipboard.writeText(this.roomId);
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
    this.sub?.unsubscribe();
    this.ws.disconnect();
  }

  formatTime(date: Date): string {
    return new Date(date).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
  }
}
