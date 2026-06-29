import { Injectable } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class UserService {
  private _username = '';

  get username(): string {
    return this._username || localStorage.getItem('username') || '';
  }

  set username(name: string) {
    this._username = name;
    localStorage.setItem('username', name);
  }

  isLoggedIn(): boolean {
    return !!this.username;
  }

  logout(): void {
    this._username = '';
    localStorage.removeItem('username');
  }
}
