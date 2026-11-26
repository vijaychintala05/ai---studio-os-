'use strict';
/* StudioOS v0.12.0 "Show it in any form": ask a question and see the answer in words with its first
   rows; show any report as a table, bar or line chart, figure tiles, a board by status, a calendar,
   a timeline or a printable page; your dashboard; save an answer as a report or a dashboard tile
   (always a ticket). The chat sends questions here and entries to the usual drafts, and asks when
   it is not sure. Charts are SVG built here (no libraries, no inline styles: strict CSP).
   Loaded after app.js, chat.js and graph.js. */

Object.assign(state, {v: {home: null, answer: null, display: null, shown: null, q: '', busy: false, tabBusy: false, calMonth: null}});

const vApi = (path, body) => api(path, body ? {method: 'POST', body: JSON.stringify(body)} : undefined);
const vNum = s => { const n = Number(String(s ?? '').replace(/[₹,]/g, '')); return Number.isFinite(n) ? n : null; };
const DISPLAY_NAMES = {table: 'Table', bar: 'Bar chart', line: 'Line chart', tiles: 'Figures', board: 'Board', calendar: 'Calendar', timeline: 'Timeline', print: 'Print'};

function vCompact(n, currency = false) {
  const pre = currency ? '₹' : '';
  const sign = n < 0 ? '-' : '';
  const a = Math.abs(n);
  if (a >= 1e7) return `${sign}${pre}${(a / 1e7).toFixed(a >= 1e8 ? 0 : 1).replace(/\.0$/, '')}Cr`;
  if (a >= 1e5) return `${sign}${pre}${(a / 1e5).toFixed(a >= 1e6 ? 0 : 1).replace(/\.0$/, '')}L`;
  if (a >= 1e3) return `${sign}${pre}${(a / 1e3).toFixed(a >= 1e4 ? 0 : 1).replace(/\.0$/, '')}K`;
  return `${sign}${pre}${a}`;
}

// ------------------------------------------------------------------ renderers (data from views_core.shape)

function vTable(r) {
  if (!r) return '';
  if (r.mode === 'figure') return vTiles({tiles: r.figures.map(f => ({label: f.label, value: f.value}))});
  if (r.mode === 'grouped') return `<div class="w-table-wrap"><table class="w-table v-table"><thead><tr>${r.group_labels.concat(r.measure_labels).map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${r.rows.map(x =>
    `<tr>${x.group.map(g => `<td>${esc(g)}</td>`).join('')}${x.values.map(v => `<td class="num">${esc(v)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  return `<div class="w-table-wrap"><table class="w-table v-table"><thead><tr>${(r.column_labels || []).map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${(r.rows || []).map(x =>
    `<tr>${x.cells.map(c => `<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}

function vTiles(s) {
  return `<div class="v-tiles">${(s.tiles || []).map(t => `<div class="v-tile"><div class="v-tile-value">${esc(t.value)}</div><div class="v-tile-label">${esc(t.label)}</div></div>`).join('')}</div>`;
}

function vBar(s) {
  const pts = (s.points || []).filter(p => vNum(p.value) !== null);
  if (!pts.length) return '<p class="muted">Nothing to chart.</p>';
  const hasCurrency = pts.some(p => String(p.text || '').includes('₹'));
  const max = Math.max(...pts.map(p => vNum(p.value)), 0) || 1, rowH = 26, labelW = 130, rightW = 110, W = 440, barW = W - labelW - rightW;
  const H = pts.length * rowH + 8;
  return `<svg class="v-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(s.title || 'Bar chart')}">${pts.map((p, i) => {
    const val = vNum(p.value);
    const w = Math.max(1, Math.round(barW * Math.max(0, val) / max)), y = 4 + i * rowH;
    const rawText = String(p.text ?? '');
    const shownText = rawText.length > 14 ? vCompact(val, hasCurrency) : rawText;
    return `<text class="v-axis" x="${labelW - 6}" y="${y + 16}" text-anchor="end">${esc(String(p.label).slice(0, 18))}</text>` +
      `<rect class="v-bar" x="${labelW}" y="${y + 4}" width="${w}" height="${rowH - 10}" rx="3"><title>${esc(p.label)}: ${esc(p.text)}</title></rect>` +
      `<text class="v-val" x="${labelW + w + 6}" y="${y + 16}">${esc(shownText)}</text>`;
  }).join('')}</svg>${s.truncated ? '<p class="muted">Showing the first 60.</p>' : ''}`;
}

function vLine(s) {
  const pts = (s.points || []).filter(p => vNum(p.value) !== null);
  if (pts.length < 2) return vBar(s);
  const hasCurrency = pts.some(p => String(p.text || '').includes('₹'));
  const W = 420, H = 200, L = 62, B = 30, T = 10, max = Math.max(...pts.map(p => vNum(p.value)), 0) || 1;
  const x = i => L + Math.round((W - L - 12) * i / (pts.length - 1)), y = v => T + Math.round((H - T - B) * (1 - v / max));
  const path = pts.map((p, i) => `${i ? 'L' : 'M'}${x(i)},${y(vNum(p.value))}`).join(' ');
  const ticks = [0, Math.floor((pts.length - 1) / 2), pts.length - 1];
  return `<svg class="v-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(s.title || 'Line chart')}">` +
    `<line class="v-grid" x1="${L}" y1="${H - B}" x2="${W - 12}" y2="${H - B}"/><text class="v-axis" x="${L - 6}" y="${T + 8}" text-anchor="end">${esc(vCompact(max, hasCurrency))}</text>` +
    `<text class="v-axis" x="${L - 6}" y="${H - B}" text-anchor="end">${hasCurrency ? '₹0' : '0'}</text><path class="v-line" d="${path}"/>` +
    pts.map((p, i) => `<circle class="v-dot" cx="${x(i)}" cy="${y(vNum(p.value))}" r="3"><title>${esc(p.label)}: ${esc(p.text)}</title></circle>`).join('') +
    ticks.map(i => `<text class="v-axis" x="${x(i)}" y="${H - 10}" text-anchor="middle">${esc(String(pts[i].label).slice(5, 10) || pts[i].label)}</text>`).join('') + '</svg>';
}

function vBoard(s) {
  return `<div class="v-board">${(s.lanes || []).map(l => `<section class="v-lane"><div class="v-lane-head">${esc(l.name)} <span class="muted">${Number(l.count)}</span></div>${l.cards.map(c =>
    `<button class="v-card cx-link" data-v="open" data-id="${Number(c.id)}">${esc(c.label)}</button>`).join('')}</section>`).join('')}</div>`;
}

function vShiftMonth(ym, delta) {
  const [yy, mm] = String(ym || '').split('-').map(Number);
  if (!yy) return ym;
  const d = new Date(Date.UTC(yy, mm - 1 + delta, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
}

function vCalendar(s) {
  const activeMonth = state.v.calMonth || s.month;
  const [yy, mm] = String(activeMonth || '').split('-').map(Number);
  if (!yy) return '<p class="muted">No dates to show.</p>';
  const first = new Date(Date.UTC(yy, mm - 1, 1)), days = new Date(Date.UTC(yy, mm, 0)).getUTCDate(), lead = (first.getUTCDay() + 6) % 7;
  const by = {}; (s.days || []).forEach(d => { by[d.date] = d; });
  const cells = [];
  for (let i = 0; i < lead; i++) cells.push('<div class="v-day v-day-empty"></div>');
  for (let d = 1; d <= days; d++) {
    const key = `${yy}-${String(mm).padStart(2, '0')}-${String(d).padStart(2, '0')}`, e = by[key];
    cells.push(`<div class="v-day${e ? ' v-day-has' : ''}"><div class="v-day-n">${d}</div>${e ? `<div class="v-day-count">${Number(e.count)}</div>${e.items.slice(0, 2).map(x => x.id ? `<button type="button" class="v-day-item cx-link" data-v="open" data-id="${Number(x.id)}">${esc(x.label)}</button>` : `<div class="v-day-item">${esc(x.label)}</div>`).join('')}` : ''}</div>`);
  }
  const other = (s.days || []).filter(d => !d.date.startsWith(activeMonth)).length;
  return `<div class="v-cal-head row-actions"><button type="button" class="btn btn-secondary btn-sm" data-v="cal-prev" data-month="${esc(activeMonth)}" aria-label="Previous month">← Prev</button><span>${esc(first.toLocaleString('en-IN', {month: 'long', year: 'numeric', timeZone: 'UTC'}))}</span><button type="button" class="btn btn-secondary btn-sm" data-v="cal-next" data-month="${esc(activeMonth)}" aria-label="Next month">Next →</button></div><div class="v-cal">${['M', 'T', 'W', 'T', 'F', 'S', 'S'].map(d => `<div class="v-dow">${d}</div>`).join('')}${cells.join('')}</div>` +
    (other ? `<p class="muted">${other} more day${other === 1 ? '' : 's'} with records outside this month.</p>` : '');
}

function vTimeline(s) {
  const bars = s.bars || [];
  if (!bars.length) return '<p class="muted">No records with both dates.</p>';
  const t0 = Date.parse(s.start), t1 = Date.parse(s.end) + 864e5, W = 340, L = 110, rowH = 22, H = bars.length * rowH + 24;
  const x = t => L + Math.round((W - L - 6) * (t - t0) / (t1 - t0));
  return `<svg class="v-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Timeline">` +
    `<text class="v-axis" x="${L}" y="12">${esc(s.start)}</text><text class="v-axis" x="${W - 6}" y="12" text-anchor="end">${esc(s.end)}</text>` +
    bars.map((b, i) => { const y = 18 + i * rowH, a = x(Date.parse(b.start)), e = x(Date.parse(b.end) + 864e5);
      return `<text class="v-axis" x="${L - 6}" y="${y + 14}" text-anchor="end">${esc(String(b.label).slice(0, 16))}</text><rect class="v-bar" x="${a}" y="${y + 4}" width="${Math.max(3, e - a)}" height="${rowH - 8}" rx="3"><title>${esc(b.label)}: ${esc(b.start)} to ${esc(b.end)}</title></rect>`;
    }).join('') + `</svg>${s.skipped ? `<p class="muted">${Number(s.skipped)} without both dates are not shown.</p>` : ''}`;
}

function vRender(s) {
  if (!s) return '';
  if (s.kind === 'error') return `<p class="muted">${esc(s.message)}</p>`;
  if (s.kind === 'bar') return vBar(s);
  if (s.kind === 'line') return vLine(s);
  if (s.kind === 'tiles') return vTiles(s);
  if (s.kind === 'board') return vBoard(s);
  if (s.kind === 'calendar') return vCalendar(s);
  if (s.kind === 'timeline') return vTimeline(s);
  if (s.kind === 'print') return `<div class="v-print"><h2>${esc(s.title || '')}</h2>${vTable(s.result)}<p class="muted">Printed from StudioOS on ${esc(new Date().toISOString().slice(0, 10))}. Only records the printer may see.</p></div>`;
  return vTable(s.result);
}

// ------------------------------------------------------------------ the screen

function vAnswerPanel() {
  if (state.v.busy) return '<section class="panel v-pad"><div class="loading" role="status">Searching your records…</div></section>';
  const a = state.v.answer;
  if (!a) return '';
  if (a.status !== 'ok') return `<section class="panel v-pad"><p><strong>I need a little more.</strong> ${esc(a.ask)}</p><p class="muted">Try: “How many open issues by owner”, “Total hours this week by person”, “List delayed milestones”.</p></section>`;
  const opts = a.displays || [{kind: 'table'}];
  const cur = state.v.display || opts[0];
  return `<section class="panel v-answer"><div class="panel-head"><div><div class="panel-title">${esc(a.report.title)}</div><div class="panel-sub" id="vWords">${esc(a.words)}</div></div></div>
    <div class="v-pad"><div class="v-forms" role="tablist">${opts.map((d, i) => `<button type="button" role="tab" aria-selected="${cur.kind === d.kind}" class="g-tab ${cur.kind === d.kind ? 'active' : ''}" data-v="form" data-i="${i}">${esc(DISPLAY_NAMES[d.kind])}</button>`).join('')}</div>
    <div class="v-view" id="vView">${state.v.tabBusy ? '<div class="loading" role="status">Updating view…</div>' : (state.v.shown ? vRender(state.v.shown) : vTable(a.result))}</div>
    <p class="muted">${a.result.mode === 'figure' ? '' : `First ${Math.min(10, a.total_rows)} of ${Number(a.total_rows)} rows shown.`} Read by the ${a.source === 'ai' ? 'AI model' : 'offline reader'}; nothing has been saved.</p>
    ${state.user?.role !== 'viewer' ? `<div class="v-save"><label>Save for<select class="form-input" id="vVisible"><option value="">Everyone</option><option value="admin,manager">Admin and managers</option><option value="admin,manager,accounts">Admin, managers, accounts</option></select></label>
      <button class="btn btn-primary btn-sm" data-v="save-report">Save as report</button>${isAdmin() ? ' <button class="btn btn-secondary btn-sm" data-v="save-tile">Add to my dashboard</button>' : ''}${cur.kind === 'print' ? ' <button class="btn btn-secondary btn-sm" data-v="print">Print</button>' : ''}</div>` : ''}</div></section>`;
}

function vHomePanel() {
  const h = state.v.home;
  if (!h) return '<div class="loading">Loading your dashboard…</div>';
  if (!h.dashboard) return `<section class="panel v-pad"><p class="muted">No dashboard for your role yet.${isAdmin() ? ' Ask a question below, save it as a report, then “Add to my dashboard”.' : ' The Admin can make one.'}</p></section>`;
  return `<div class="v-dash-head"><h2>${esc(h.dashboard.title)}</h2></div><div class="v-dash">${h.tiles.map(t =>
    `<section class="panel v-dash-tile"><div class="panel-head"><div class="panel-title">${esc(t.title)}</div></div><div class="v-pad">${vRender(t.view)}</div></section>`).join('')}</div>`;
}

function viewsView() {
  if (!state.v.home) vApi('/api/views/home').then(h => { state.v.home = h; render(); }).catch(err => { state.v.home = {dashboard: null, tiles: []}; notify(err.message, true); });
  const myTime = typeof navCanOpen === 'function' && navCanOpen('mytime') ? '<p class="v-shortcuts"><button type="button" class="btn btn-secondary btn-sm" data-view="mytime">My time</button></p>' : '';   // a quick way to the timer and your hours
  return head('Ask and dashboards', 'Ask about your records in plain words. The answer is shown first; saving it is a ticket.') + myTime +
    vHomePanel() + `<section class="panel v-pad v-askbox"><form id="vAsk" class="v-ask"><input class="form-input" id="vQ" name="q" maxlength="300" placeholder="e.g. Open issues by owner" value="${esc(state.v.q)}" aria-label="Your question"><button class="btn btn-primary" type="submit" ${state.v.busy ? 'disabled' : ''}>Ask</button></form></section>` + vAnswerPanel();
}

async function vAsk(q) {
  state.v.q = q; state.v.busy = true; state.v.display = null; state.v.shown = null; state.v.calMonth = null; render();
  try { state.v.answer = await vApi('/api/views/ask', {question: q}); }
  catch (err) { notify(err.message, true); }
  finally { state.v.busy = false; render(); }
}

function vSlug(t) { const s = String(t).toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 40); return /^[a-z]/.test(s) && s.length > 1 ? s : 'report_' + s; }

const _vRender = render;
render = function () {
  if (state.view === 'insights') {
    document.body.classList.remove('chat-mode');
    updateIdentity();
    $('mainContent').innerHTML = viewsView();
    $('breadcrumb').textContent = 'Ask and dashboards';
    document.querySelectorAll('.nav-link').forEach(b => b.classList.toggle('active', b.dataset.view === state.view));
    return;
  }
  _vRender();
};

document.addEventListener('submit', e => {
  if (e.target.id !== 'vAsk') return;
  e.preventDefault();
  const q = String(new FormData(e.target).get('q') || '').trim();
  if (q) vAsk(q);
});

document.addEventListener('click', async e => {
  if (e.target.closest('[data-view="insights"]')) { state.v.home = null; return; }
  const b = e.target.closest('[data-v]');
  if (!b) return;
  e.preventDefault();
  const v = state.v, a = v.answer;
  try {
    if (b.dataset.v === 'form') {
      v.display = a.displays[Number(b.dataset.i)];
      v.calMonth = null;
      v.tabBusy = true; render();
      try {
        v.shown = await vApi('/api/views/show', {definition: a.report, display: v.display});
      } finally {
        v.tabBusy = false; render();
      }
      return;
    }
    if (b.dataset.v === 'cal-prev' || b.dataset.v === 'cal-next') {
      v.calMonth = vShiftMonth(b.dataset.month, b.dataset.v === 'cal-prev' ? -1 : 1);
      render(); return;
    }
    if (b.dataset.v === 'print') { window.print(); return; }
    if (b.dataset.v === 'open') { state.g.record = null; switchView('work'); await gOpen(b.dataset.id); return; }
    if (b.dataset.v === 'save-report' || b.dataset.v === 'save-tile') {
      const vis = ($('vVisible')?.value || '').split(',').filter(Boolean);
      const def = {...a.report, key: vSlug(a.report.title) + '_' + Date.now().toString(36).slice(-4)};
      if (v.display && v.display.kind !== 'table') def.display = v.display;
      if (vis.length) def.visible_to = vis;
      b.disabled = true;
      const r = await vApi('/api/universal/proposals', {kind: 'metadata_report', data: def, evidence: 'Saved from the question: ' + v.q});
      if (b.dataset.v === 'save-tile') {
        const boards = (await vApi('/api/views/dashboards')).dashboards;
        const mine = boards.find(d => d.roles.includes('admin'));
        const board = mine ? {key: mine.key, title: mine.title, roles: mine.roles, tiles: mine.tiles.concat([{report: def.key}]).slice(-12)}
          : {key: 'admin_home', title: 'Admin dashboard', roles: ['admin'], tiles: [{report: def.key}]};
        await vApi('/api/universal/proposals', {kind: 'metadata_dashboard', data: board, evidence: 'Add a tile: ' + a.report.title});
        notify(`Tickets opened: the report (#${r.ticket_id}) and the dashboard tile. Approve the report first.`);
      } else notify(`Ticket #${r.ticket_id} opened. The report is saved once it is approved.`);
      return;
    }
  } catch (err) { b.disabled = false; notify(err.message, true); }
});

// ------------------------------------------------------------------ the chat: question, entry, or ask

const _vMessage = cxMessage;
cxMessage = function (m, i, lastCardIndex) {
  if (m.answer) {
    const a = m.answer;
    return `<div class="cx-msg ai"><div class="cx-avatar">✦</div><div class="cx-body v-chat-answer"><div class="cx-text"><strong>${esc(a.report.title)}</strong><br><span class="muted">${esc(a.words)}</span></div>${vTable(a.result)}<div class="chat-actions"><button class="btn btn-secondary btn-sm" data-v-chat="open" data-q="${esc(m.q)}">Show as chart or save</button></div></div></div>`;
  }
  if (m.whichKind) {
    return `<div class="cx-msg ai"><div class="cx-avatar">✦</div><div class="cx-body"><div class="cx-text">Is this a question about your records, or something to record?</div><div class="chat-actions"><button class="btn btn-secondary btn-sm" data-v-chat="question" data-q="${esc(m.whichKind)}">A question</button> <button class="btn btn-secondary btn-sm" data-v-chat="entry" data-q="${esc(m.whichKind)}">Something to record</button></div></div></div>`;
  }
  return _vMessage(m, i, lastCardIndex);
};

async function vChatQuestion(text) {
  const r = await vApi('/api/views/ask', {question: text});
  if (r.status === 'ok') { state.messages.push({role: 'assistant', answer: r, q: text}); return true; }
  return false;
}

const _vSend = sendChat;
sendChat = async function (content) {
  const text = String(content ?? '').trim();
  if (!text || state.attachments.length || state.thinking) return _vSend(content);
  let kind = 'entry';
  // Classification is part of this send, so another conversation cannot replace
  // its context before the reader starts.
  state.thinking = true; render();
  try { kind = (await vApi('/api/views/classify', {message: text})).kind; } catch (e) { kind = 'entry'; }
  finally { state.thinking = false; }
  if (kind !== 'entry' && typeof cxLooksLikeEdit === 'function' && cxLooksLikeEdit(text)) kind = 'entry';   // an edit of the open draft
  if (kind === 'entry') return _vSend(content);
  state.draftText = '';
  state.messages.push({role: 'user', reply: text});
  if (kind === 'unsure') { state.messages.push({role: 'assistant', whichKind: text}); render(); return; }
  state.thinking = true; render();
  let answered = false;
  try { answered = await vChatQuestion(text); } catch (e) { answered = false; }
  state.thinking = false;
  if (!answered) { state.messages.pop(); return _vSend(content); }   // older questions (projects, budgets) still go to the chat
  render();
};

document.addEventListener('click', async e => {
  const b = e.target.closest('[data-v-chat]');
  if (!b) return;
  e.preventDefault();
  const q = b.dataset.q;
  if (b.dataset.vChat === 'open') { switchView('insights'); await vAsk(q); return; }
  const i = state.messages.findIndex(m => m.whichKind === q);
  if (i >= 0) state.messages.splice(i - 1, 2);
  if (b.dataset.vChat === 'entry') { await _vSend(q); return; }
  state.messages.push({role: 'user', reply: q}); state.thinking = true; render();
  let ok = false;
  try { ok = await vChatQuestion(q); } catch (err) { ok = false; }
  state.thinking = false;
  if (!ok) state.messages.push({role: 'assistant', reply: 'I could not turn that into a report. Try “how many open issues by owner”.'});
  render();
});
