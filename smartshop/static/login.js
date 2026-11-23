'use strict';

const password = document.querySelector('#password');
const toggle = document.querySelector('#password-toggle');

toggle.addEventListener('click', () => {
  const show = password.type === 'password';
  password.type = show ? 'text' : 'password';
  toggle.textContent = show ? toggle.dataset.hide : toggle.dataset.show;
});
toggle.hidden = false;
