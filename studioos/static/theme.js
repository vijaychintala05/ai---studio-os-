'use strict';
/* Theme choice: light (default), dark or sunlight. Loaded in <head> so the theme is set before the page paints.
   The choice is kept in this browser only; storage may be blocked, so every access is guarded. */
(function () {
  var THEMES = ['light', 'dark', 'sunlight'];
  function systemTheme() {
    try { return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'; } catch (e) { return 'light'; }
  }
  function read() {
    try {
      var v = localStorage.getItem('studioos-theme');
      if (THEMES.indexOf(v) >= 0) return v;
    } catch (e) { /* storage unavailable */ }
    return systemTheme();
  }
  function apply(t) { document.documentElement.setAttribute('data-theme', THEMES.indexOf(t) >= 0 ? t : 'light'); }
  function syncButtons(t) {
    var b = document.querySelectorAll('[data-theme-set]');
    for (var i = 0; i < b.length; i++) b[i].setAttribute('aria-pressed', String(b[i].getAttribute('data-theme-set') === t));
  }
  window.setStudioTheme = function (t) {
    if (THEMES.indexOf(t) < 0) return;
    apply(t);
    try { localStorage.setItem('studioos-theme', t); } catch (e) { /* the choice just lasts until the page closes */ }
    syncButtons(t);
  };
  apply(read());
  window.addEventListener('storage', function (e) {
    if (e.key === 'studioos-theme') {
      var t = read();
      apply(t);
      syncButtons(t);
    }
  });
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('[data-theme-set]');
    if (b) window.setStudioTheme(b.getAttribute('data-theme-set'));
  });
  document.addEventListener('DOMContentLoaded', function () {
    var t = read();
    apply(t);
    syncButtons(t);
  });
}());
