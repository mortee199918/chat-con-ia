import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface Room {
  id: string;
  name: string;
  type: 'ai' | 'peer';
  users: string[];
}

@Injectable({ providedIn: 'root' })
export class RoomService {
  private api = 'http://localhost:8000';

  constructor(private http: HttpClient) {}

  getRooms(): Observable<Room[]> {
    return this.http.get<Room[]>(`${this.api}/rooms`);
  }

  createRoom(name: string, type: 'ai' | 'peer'): Observable<Room> {
    return this.http.post<Room>(`${this.api}/rooms`, { name, type });
  }
}
