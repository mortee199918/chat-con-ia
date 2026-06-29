import { Routes } from '@angular/router';
import { Login } from './components/login/login';
import { Lobby } from './components/lobby/lobby';
import { Chat } from './components/chat/chat';

export const routes: Routes = [
  { path: '', component: Login },
  { path: 'lobby', component: Lobby },
  { path: 'room/:id', component: Chat },
  { path: '**', redirectTo: '' },
];
