import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, NavigationEnd } from '@angular/router';
import { RoomService, Room } from '../../services/room';
import { UserService } from '../../services/user.service';
import { Subscription, filter } from 'rxjs';

@Component({
  selector: 'app-lobby',
  imports: [CommonModule, FormsModule],
  templateUrl: './lobby.html',
  styleUrl: './lobby.scss',
})
export class Lobby implements OnInit, OnDestroy {
  rooms: Room[] = [];
  showModal = false;
  newRoomName = '';
  newRoomType: 'ai' | 'peer' = 'ai';
  loading = true;
  loadingTooLong = false;

  private loadingTimer: ReturnType<typeof setTimeout> | null = null;
  private refreshInterval: ReturnType<typeof setInterval> | null = null;
  private routerSub!: Subscription;

  get username(): string { return this.userService.username; }

  constructor(
    private roomService: RoomService,
    private userService: UserService,
    private router: Router,
  ) {
    if (!this.userService.isLoggedIn()) {
      this.router.navigate(['/']);
    }
  }

  ngOnInit(): void {
    this.loadRooms();

    // Auto-refresh silencioso cada 15 segundos
    this.refreshInterval = setInterval(() => this.loadRooms(true), 15000);

    this.routerSub = this.router.events
      .pipe(filter((e) => e instanceof NavigationEnd && e.urlAfterRedirects === '/lobby'))
      .subscribe(() => this.loadRooms());
  }

  ngOnDestroy(): void {
    this.routerSub?.unsubscribe();
    if (this.loadingTimer) clearTimeout(this.loadingTimer);
    if (this.refreshInterval) clearInterval(this.refreshInterval);
  }

  loadRooms(silent = false): void {
    if (!silent) {
      this.loading = true;
      this.loadingTooLong = false;
      this.loadingTimer = setTimeout(() => {
        if (this.loading) this.loadingTooLong = true;
      }, 5000);
    }

    this.roomService.getRooms().subscribe({
      next: (rooms) => {
        this.rooms = rooms;
        if (!silent) {
          this.loading = false;
          if (this.loadingTimer) clearTimeout(this.loadingTimer);
        }
      },
      error: () => {
        if (!silent) {
          this.loading = false;
          if (this.loadingTimer) clearTimeout(this.loadingTimer);
        }
      },
    });
  }

  createRoom(): void {
    const name = this.newRoomName.trim();
    if (!name) return;
    this.roomService.createRoom(name, this.newRoomType).subscribe((room) => {
      this.showModal = false;
      this.newRoomName = '';
      this.router.navigate(['/room', room.id], { queryParams: { name: room.name } });
    });
  }

  joinRoom(id: string, name: string): void {
    this.router.navigate(['/room', id], { queryParams: { name } });
  }

  logout(): void {
    this.userService.logout();
    this.router.navigate(['/']);
  }
}
