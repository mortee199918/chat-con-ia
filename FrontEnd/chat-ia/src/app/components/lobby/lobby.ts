import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { RoomService, Room } from '../../services/room';
import { UserService } from '../../services/user.service';

@Component({
  selector: 'app-lobby',
  imports: [CommonModule, FormsModule],
  templateUrl: './lobby.html',
  styleUrl: './lobby.scss',
})
export class Lobby implements OnInit {
  rooms: Room[] = [];
  showModal = false;
  newRoomName = '';
  newRoomType: 'ai' | 'peer' = 'ai';

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
  }

  loadRooms(): void {
    this.roomService.getRooms().subscribe((rooms) => (this.rooms = rooms));
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
