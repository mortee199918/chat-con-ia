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
  private routerSub!: Subscription;

  get username(): string {
    return this.userService.username;
  }

  constructor(
    private roomService: RoomService,
    private userService: UserService,
    private router: Router
  ) {
    if (!this.userService.isLoggedIn()) {
      this.router.navigate(['/']);
    }
  }

  ngOnInit(): void {
    this.loadRooms();
    this.routerSub = this.router.events
      .pipe(filter((e) => e instanceof NavigationEnd && e.urlAfterRedirects === '/lobby'))
      .subscribe(() => this.loadRooms());
  }

  ngOnDestroy(): void {
    this.routerSub?.unsubscribe();
    if (this.loadingTimer) clearTimeout(this.loadingTimer);
  }

  loadRooms(): void {
    this.loading = true;
    this.loadingTooLong = false;

    this.loadingTimer = setTimeout(() => {
      if (this.loading) this.loadingTooLong = true;
    }, 5000);

    this.roomService.getRooms().subscribe({
      next: (rooms) => {
        this.rooms = rooms;
        this.loading = false;
        if (this.loadingTimer) clearTimeout(this.loadingTimer);
      },
      error: () => {
        this.loading = false;
        if (this.loadingTimer) clearTimeout(this.loadingTimer);
      }
    });
  }

  createRoom(): void {
    const name = this.newRoomName.trim();
    if (!name) return;
    this.roomService.createRoom(name, this.newRoomType).subscribe((room) => {
      this.showModal = false;
      this.newRoomName = '';
      this.router.navigate(['/room', room.id]);
    });
  }

  joinRoom(id: string): void {
    this.router.navigate(['/room', id]);
  }

  logout(): void {
    this.userService.logout();
    this.router.navigate(['/']);
  }
}
