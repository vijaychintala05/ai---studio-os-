'use strict';
/* StudioOS icons (design plan: one outline style, drawn to the Lucide grid rules): a 24 by 24 canvas, a 2 px stroke, round caps and joins,
   drawn in the current text colour, so they follow every theme. These are StudioOS's own drawings, inline, with no icon font and no
   outside source (strict CSP). An icon never carries meaning alone: use it beside a label, or give the button an accessible name.
   icon(name, size) returns the markup; sizes in the plan are 16, 20, 24 and 32. Loaded right after app.js. */

const ICONS = {
  // tabs and navigation
  home: '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>',
  inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5h13L22 12v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6z"/>',
  capture: '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 3v4M17 5h4"/><path d="M5 17v4M3 19h4"/>',
  projects: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  me: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  books: '<path d="M6 4h12"/><path d="M6 9h12"/><path d="M8 4a5 5 0 0 1 0 10H6l8 7"/>',
  // actions
  search: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
  scope: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  filter: '<path d="M3 5h18l-7 8v6l-4 2v-8z"/>',
  eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M5 19l1.5-1.5M17.5 6.5L19 5"/>',
  moon: '<path d="M20 14.5A8 8 0 1 1 9.5 4 6.5 6.5 0 0 0 20 14.5z"/>',
  contrast: '<circle cx="12" cy="12" r="9"/><path d="M12 3v18"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  // fixed meanings (design plan): each meaning has one icon
  done: '<circle cx="12" cy="12" r="9"/><path d="M8.5 12.5l2.5 2.5 4.5-5"/>',
  overdue: '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2 2"/><path d="M5 3L2 6M19 3l3 3"/>',
  attention: '<path d="M12 3L2 20h20z"/><path d="M12 10v4"/><path d="M12 17.5v.5"/>',
  blocked: '<path d="M8 2h8l6 6v8l-6 6H8l-6-6V8z"/><path d="M9 9l6 6M15 9l-6 6"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4"/><path d="M12 8v.5"/>',
  draft: '<path d="M17 3l4 4L8 20l-5 1 1-5z"/>',
  locked: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
  offline: '<path d="M3 3l18 18"/><path d="M9 5.5A6 6 0 0 1 19 9a4 4 0 0 1 2 6.5"/><path d="M5.5 18A4 4 0 0 1 6 10"/>',
  // StudioOS site work
  snag: '<path d="M12 21s-7-6-7-11a7 7 0 0 1 14 0c0 5-7 11-7 11z"/><path d="M11 6l2 3-2 2 2 3"/>',
  visit: '<path d="M3 17a9 9 0 0 1 18 0"/><path d="M2 17h20v3H2z"/><path d="M12 8v4"/>',
  report: '<rect x="6" y="4" width="12" height="17" rx="2"/><path d="M9 4h6v3H9z"/><path d="M9 12h6M9 16h4"/>',
};

function icon(name, size = 24) {
  const body = ICONS[name];
  if (!body) return '';
  return `<svg class="icon" viewBox="0 0 24 24" width="${Number(size)}" height="${Number(size)}" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${body}</svg>`;
}
