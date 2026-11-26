'use strict';
/* Time: add, edit and submit entries and record leave (Home -> My time); approve, send back or reject
   (Inbox -> Timesheets); working days, holidays and cost rates (Settings -> Working time). Everything drafts a
   change request through POST /api/time/propose. Loaded after newwork.js and gapkit.js. */

const TW_STATUS = {draft: ['Not submitted', 'warn'], submitted: ['Waiting for a manager', 'warn'], approved: ['Approved', 'good'], rejected: ['Rejected', 'critical']};
const TW_LEAVE = [['leave', 'Leave'], ['sick', 'Sick'], ['other', 'Other']];
const TW_SETTINGS = [['time_daily_limit_minutes', 'Most time a day (minutes)'], ['time_weekly_limit_minutes', 'Most time a week (minutes)'], ['work_daily_capacity_minutes', 'Working time a day (minutes)']];
const TW_DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const twMins = m => { m = Number(m) || 0; return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')} min`; };
const twPerson = id => ((state.users || []).find(u => u.id === id) || {}).display_name || (id === state.user?.id ? 'You' : `Person #${Number(id)}`);
const twStatus = s => pill(...(TW_STATUS[s] || [s, '']));
const twTasks = () => (state.tasks || []).filter(t => t.status !== 'completed');

async function twPropose(kind, data) {
  await gkDraft('/api/time/propose', {kind, data});
  gkForget('tw:');
  if (state.nw) state.nw.time = null;
}

/* ------------------------------------------------------------ added to My time ------------------------ */
function twMyPanels() {
  if (state.user?.role === 'viewer') return '';
  const mine = gkGet('tw:mine', async () => (await api('/api/time/entries')).filter(e => e.user_id === state.user.id));
  const cal = gkGet('tw:cal', () => api('/api/time/calendar'));
  const tasks = twTasks();
  const add = gkForm('add', gkSelect('Task', 'task_id', [['', 'A general activity instead'], ...tasks.map(t => [t.id, t.title])], '') +
    gkInput('General activity (if no task)', 'activity', 'maxlength="80"') + gkInput('Date', 'work_date', 'required', 'date') +
    gkInput('Hours', 'hours', 'required inputmode="decimal" placeholder="1.5"') + gkInput('Note (optional)', 'note', 'maxlength="1000"'), 'Draft time entry');
  let list = gkWait(mine);
  if (Array.isArray(mine)) {
    list = gkTable(['Date', 'On', 'Time', 'State', ''], mine.filter(e => e.status === 'draft').map(e => [esc(e.work_date),
      e.task_id ? `Task ${Number(e.task_id)}` : esc(e.activity), esc(twMins(e.minutes)), twStatus(e.status),
      `${gkButton('submit', 'Submit', `data-id="${Number(e.id)}"`)} ${gkButton('edit', 'Change time', `data-id="${Number(e.id)}"`)}`]),
    'Nothing is waiting to be submitted.');
  }
  const leaveForm = gkForm('leave', gkInput('From', 'start_date', 'required', 'date') + gkInput('To', 'end_date', 'required', 'date') +
    gkSelect('Kind', 'kind', TW_LEAVE, 'leave') + gkInput('Note (optional)', 'note', 'maxlength="300"'), 'Draft leave');
  let leave = gkWait(cal);
  if (cal && cal.leave) {
    leave = gkTable(['From', 'To', 'Kind', ''], cal.leave.filter(l => l.user_id === state.user.id).map(l => [esc(l.start_date), esc(l.end_date), esc(l.kind),
      gkButton('cancelLeave', 'Cancel leave', `data-id="${Number(l.id)}"`)]), 'No leave recorded.');
  }
  const estimate = ['admin', 'manager', 'architect'].includes(state.user?.role) && tasks.length
    ? gkPanel('Estimate a task', 'Used by the workload warning.', gkForm('estimate', gkSelect('Task', 'task_id', tasks.map(t => [t.id, t.title]), tasks[0].id) +
      gkInput('Estimate in hours', 'hours', 'required inputmode="decimal"'), 'Draft estimate')) : '';
  return gkSections('twSection', [
    ['add', 'Add time', () => gkPanel('Add time', 'For work the timer did not catch.', add)],
    ['submit', 'Submit', () => gkPanel('Submit your time', 'Submitted time goes to a manager.', list)],
    ['leave', 'Leave', () => gkPanel('Leave', '', leave + leaveForm)],
    estimate && ['estimate', 'Estimate a task', () => estimate],
  ]);
}

/* Hours typed by a person ("1.5") to whole minutes. */
function twMinutes(raw) {
  const hours = Number(raw);
  const minutes = Math.round(hours * 60);
  if (!Number.isFinite(hours) || minutes < 1 || minutes > 100000) throw new Error('Give the time in hours, for example 1.5.');
  return minutes;
}

const twAny = {   // handlers for the panels added to My time (not a screen of its own)
  submit: {
    add: async form => {
      const v = gkValues(form);
      if (!v.task_id === !v.activity) throw new Error('Choose one: a task, or a general activity.');
      await twPropose('time_log', {...(v.task_id ? {task_id: Number(v.task_id)} : {activity: v.activity}), work_date: v.work_date,
        minutes: twMinutes(v.hours), note: v.note || '', source: 'manual'});
    },
    leave: async form => {
      const v = gkValues(form);
      await twPropose('leave_record', {user_id: state.user.id, start_date: v.start_date, end_date: v.end_date, kind: v.kind, note: v.note || ''});
    },
    estimate: async form => { const v = gkValues(form); await twPropose('task_estimate', {task_id: Number(v.task_id), minutes: twMinutes(v.hours)}); },
  },
  click: {
    submit: async el => twPropose('time_submit', {entry_id: Number(el.dataset.id)}),
    edit: async el => {
      const hours = await askText('How many hours should this entry be?', '', 'Draft change');
      if (hours === null || hours === undefined) return;
      await twPropose('time_edit', {entry_id: Number(el.dataset.id), minutes: twMinutes(hours)});
    },
    cancelLeave: async el => { if (await askConfirm('Draft cancelling this leave?', 'Draft cancellation')) await twPropose('leave_cancel', {leave_id: Number(el.dataset.id)}); },
  },
};
Object.assign(GK_SCREENS._any.click, twAny.click);
Object.assign(GK_SCREENS._any.submit, twAny.submit);

if (typeof NW_VIEWS !== 'undefined') {
  const twBase = NW_VIEWS.mytime[1];
  NW_VIEWS.mytime = ['My time', () => twBase() + twMyPanels()];
  const twRender = render;
  render = function () {
    twRender();
    if (state.view === 'mytime') gkHubBar();
  };
}

/* ------------------------------------------------------------ Timesheets (managers) ------------------- */
function twSheetsView() {
  const title = 'Timesheets';
  const rows = gkGet('tw:submitted', () => api('/api/time/entries?status=submitted'));
  let list = gkWait(rows);
  if (Array.isArray(rows)) {
    list = gkTable(['Person', 'Date', 'On', 'Time', 'Note', ''], rows.map(e => [esc(twPerson(e.user_id)), esc(e.work_date),
      e.task_id ? `Task ${Number(e.task_id)}` : esc(e.activity), esc(twMins(e.minutes)), esc(e.note || ''),
      e.user_id === state.user.id ? '<span class="muted">Your own time</span>'
        : `${gkButton('approve', 'Approve', `data-id="${Number(e.id)}"`, true)} ${gkButton('back', 'Send back', `data-id="${Number(e.id)}"`)} ${gkButton('reject', 'Reject', `data-id="${Number(e.id)}"`)}`]),
    'No time is waiting for you.');
  }
  return head(title, 'Submitted time waiting for a decision. Nobody approves their own.') + gkPanel('Waiting', '', list);
}

async function twDecide(kind, id, question) {
  const data = {entry_id: Number(id)};
  if (question) {
    const reason = await askText(question, '', 'Draft for approval');
    if (!reason || !String(reason).trim()) return;
    data.reason = String(reason).trim();
  }
  await twPropose(kind, data);
}

gkScreen('timesheets', {
  title: 'Timesheets', roles: ['admin', 'manager'], view: twSheetsView,
  click: {
    approve: el => twDecide('time_approve', el.dataset.id),
    back: el => twDecide('time_send_back', el.dataset.id, 'What should they correct?'),
    reject: el => twDecide('time_reject', el.dataset.id, 'Why is this time rejected?'),
  },
});

/* ------------------------------------------------------------ Working time settings ------------------- */
function twSettingsView() {
  const title = 'Working time';
  const settings = gkGet('tw:settings', () => api('/api/time/settings'));
  const cal = gkGet('tw:cal', () => api('/api/time/calendar'));
  let limits = gkWait(settings);
  if (settings && !settings.gkError) {
    limits = TW_SETTINGS.map(([key, label]) => gkForm('setting', gkInput(label, 'value', 'required inputmode="numeric"', 'text', settings[key]),
      'Draft change', `data-key="${key}"`)).join('') +
      `<p class="muted">Weekly days off: ${esc((settings.work_week_off || []).map(d => TW_DAYS[d]).join(', ') || 'none')}</p>` +
      gkForm('weekoff', TW_DAYS.map((d, i) => `<label class="gk-check"><input type="checkbox" name="day${i}" value="${i}"${(settings.work_week_off || []).includes(i) ? ' checked' : ''}> ${d}</label>`).join(''), 'Draft days off');
  }
  let holidays = gkWait(cal);
  if (cal && cal.holidays) {
    holidays = gkTable(['Date', 'Holiday', ''], cal.holidays.map(h => [esc(h.date), esc(h.name), isAdmin() ? gkButton('unholiday', 'Remove', `data-id="${Number(h.id)}"`) : '']), 'No holidays recorded.') +
      (isAdmin() ? gkForm('holiday', gkInput('Date', 'date', 'required', 'date') + gkInput('Name', 'name', 'required maxlength="120"'), 'Draft holiday') : '');
  }
  const rates = gkGet('tw:rates', () => api('/api/time/rates'));
  const people = (state.users || []).filter(u => u.active !== false);
  let rateList = gkWait(rates);
  if (Array.isArray(rates)) {
    rateList = gkTable(['Person', 'Per hour', 'From'], rates.map(r => [esc(twPerson(r.user_id)), esc(gkRs(r.rate_paise_per_hour)), esc(r.effective_from)]), 'No cost rate recorded.') +
      (people.length ? gkForm('rate', gkSelect('Person', 'user_id', people.map(u => [u.id, u.display_name]), people[0].id) +
        gkInput('Cost per hour (₹)', 'rupees', 'required inputmode="decimal"') + gkInput('Applies from', 'effective_from', 'required', 'date'), 'Draft rate') : '');
  }
  return head(title, 'Limits, days off, holidays and what an hour costs.') + gkSections('wtSection', [
    isAdmin() && ['limits', 'Limits and days off', () => gkPanel('Limits and days off', '', limits)],
    ['holidays', 'Holidays', () => gkPanel('Holidays', '', holidays)],
    ['rates', 'Cost rates', () => gkPanel('Cost rates', 'Seen only by roles that see money.', rateList)],
  ]);
}

gkScreen('worktime', {
  title: 'Working time', roles: ['admin'], view: twSettingsView,
  click: {unholiday: async el => { if (await askConfirm('Draft removing this holiday?', 'Draft removal')) await twPropose('holiday_remove', {holiday_id: Number(el.dataset.id)}); }},
  submit: {
    setting: async form => { const v = gkValues(form); await twPropose('time_setting', {key: form.dataset.key, value: Number(v.value)}); },
    weekoff: async form => { await twPropose('time_setting', {key: 'work_week_off', value: Object.values(gkValues(form)).map(Number).sort()}); },
    holiday: async form => { const v = gkValues(form); await twPropose('holiday_add', {date: v.date, name: v.name}); },
    rate: async form => {
      const v = gkValues(form), paise = gkPaise(v.rupees);
      if (!paise) throw new Error('Give the cost per hour in rupees, for example 450.');
      await twPropose('rate_set', {user_id: Number(v.user_id), rate_paise_per_hour: paise, effective_from: v.effective_from});
    },
  },
});
