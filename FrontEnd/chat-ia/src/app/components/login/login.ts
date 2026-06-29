import { Component } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { UserService } from '../../services/user.service';

@Component({
  selector: 'app-login',
  imports: [FormsModule],
  templateUrl: './login.html',
  styleUrl: './login.scss',
})
export class Login {
  username = '';

  constructor(private userService: UserService, private router: Router) {
    if (this.userService.isLoggedIn()) {
      this.router.navigate(['/lobby']);
    }
  }

  enter(): void {
    const name = this.username.trim();
    if (!name) return;
    this.userService.username = name;
    this.router.navigate(['/lobby']);
  }

  onKeyDown(e: KeyboardEvent): void {
    if (e.key === 'Enter') this.enter();
  }
}
