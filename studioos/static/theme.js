'use strict';
/* Theme choice: light (default), dark or sunlight. Loaded in <head> so the theme is set before the page paints.
   The choice is kept in this browser only; storage may be blocked, so every access is guarded. */
(function () {
  var THEMES = ['light', 'dark', 'sunlight'];
  function read() { try { var v = localStorage.getItem('studioos-theme'); return THEMES.indexOf(v) >= 0 ? v : 'light'; } catch (e) { return 'light'; } }
  function apply(t) { document.documentElement.setAttribute('data-theme', THEMES.indexOf(t) >= 0 ? t : 'light'); }
  window.setStudioTheme = function (t) {
    if (THEMES.indexOf(t) < 0) return;
    apply(t);
    try { localStorage.setItem('studioos-theme', t); } catch (e) { /* the choice just lasts until the page closes */ }
    var b = document.querySelectorAll('[data-theme-set]');
    for (var i = 0; i < b.length; i++) b[i].setAttribute('aria-pressed', String(b[i].getAttribute('data-theme-set') === t));
  };
  apply(read());
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('[data-theme-set]');
    if (b) window.setStudioTheme(b.getAttribute('data-theme-set'));
  });
  document.addEventListener('DOMContentLoaded', function () { window.setStudioTheme(read()); });
}());
