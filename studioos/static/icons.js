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
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  chevron: '<path d="M15 5l-7 7 7 7"/>',
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
  // site work, continued
  gang: '<circle cx="6" cy="9" r="2.5"/><circle cx="12" cy="7" r="2.5"/><circle cx="18" cy="9" r="2.5"/><path d="M2 20a4 4 0 0 1 8 0M8 18a4 4 0 0 1 8 0M14 20a4 4 0 0 1 8 0"/>',
  measure: '<rect x="3" y="8" width="18" height="8" rx="1"/><path d="M7 8v3M11 8v4M15 8v3M19 8v4"/>',
  handover: '<circle cx="8" cy="8" r="4"/><path d="M11 11l9 9M16 16l2-2M19 19l2-2"/>',
  // design
  sheet: '<rect x="4" y="3" width="16" height="18" rx="1"/><path d="M4 16h16M10 16v5"/>',
  revision: '<path d="M5 3h10l4 4v14H5z"/><path d="M9 12a2 2 0 0 1 3-1 2 2 0 0 1 3 1 2 2 0 0 1 0 3H9a2 2 0 0 1 0-3z"/>',
  view3d: '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M12 12l8-4.5M12 12v9M12 12L4 7.5"/>',
  swatch: '<circle cx="12" cy="12" r="9"/><circle cx="8" cy="10" r="1.5"/><circle cx="12" cy="7.5" r="1.5"/><circle cx="16" cy="10" r="1.5"/><path d="M12 21a2 2 0 0 1 0-4h2a3 3 0 0 0 3-3"/>',
  moodboard: '<rect x="3" y="3" width="8" height="10" rx="1"/><rect x="13" y="3" width="8" height="6" rx="1"/><rect x="13" y="11" width="8" height="10" rx="1"/><rect x="3" y="15" width="8" height="6" rx="1"/>',
  // materials
  tile: '<rect x="3" y="3" width="18" height="18" rx="1"/><path d="M12 3v18M3 12h18"/>',
  plywood: '<path d="M3 9l9-4 9 4-9 4z"/><path d="M3 14l9 4 9-4"/>',
  laminate: '<rect x="3" y="6" width="18" height="12" rx="1"/><path d="M3 10h18M3 14h18"/>',
  paint: '<rect x="4" y="3" width="14" height="5" rx="1"/><path d="M18 5h2v5h-8v3"/><rect x="10" y="13" width="4" height="8" rx="1"/>',
  hardware: '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.7 2.7-2.4-.6-.6-2.4z"/>',
  electrical: '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
  plumbing: '<path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z"/>',
  ceiling: '<path d="M3 5h18"/><path d="M5 5v3M12 5v3M19 5v3"/><rect x="3" y="8" width="18" height="6" rx="1"/><path d="M9 8v6M15 8v6"/>',
  boq: '<path d="M4 6h10M4 12h10M4 18h10"/><path d="M18 5v14M16 8h2M16 12h2M16 16h2"/>',
  // money
  payment: '<circle cx="12" cy="12" r="9"/><path d="M9 8h6M9 11h6M10 8a3 3 0 0 1 0 6h-1l4 3"/>',
  bill: '<path d="M6 3h12v18l-3-2-3 2-3-2-3 2z"/><path d="M9 8h6M9 12h6"/>',
  reconcile: '<path d="M6 3h9l4 4v14H6z"/><path d="M15 3v4h4"/><path d="M9 14l2 2 4-4"/>',
  periodlock: '<rect x="4" y="12" width="12" height="9" rx="2"/><path d="M7 12V9a3 3 0 0 1 6 0v3"/><path d="M19 4h-3M19 7h-3M16 4a2 2 0 0 1 0 3.5l3 3"/>',
  // kinds of record
  task: '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M8.5 12l2.5 2.5 4.5-5"/>',
  vendor: '<path d="M2 6h11v10H2z"/><path d="M13 9h5l3 3v4h-8z"/><circle cx="6" cy="18" r="2"/><circle cx="17" cy="18" r="2"/>',
};

function icon(name, size = 24) {
  const body = ICONS[name];
  if (!body) return '';
  return `<svg class="icon" viewBox="0 0 24 24" width="${Number(size)}" height="${Number(size)}" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${body}</svg>`;
}
