import { Component } from '@angular/core';
import { Chat } from './components/chat/chat';

@Component({
  selector: 'app-root',
  imports: [Chat],
  template: '<app-chat />',
})
export class App {}
