const csrf = document.querySelector('meta[name="csrf-token"]').content;
const state = {calendars: [], preview: null, reminders: [], presets: [], loaded: false};
const $ = id => document.getElementById(id);
const selected = element => [...element.selectedOptions].map(option => option.value);
const nullableNumber = id => $(id).value === '' ? null : Number($(id).value);

async function api(path, options = {}) {
  const headers = {...(options.headers || {})};
  if (options.body) headers['Content-Type'] = 'application/json';
  if ((options.method || 'GET') !== 'GET') headers['X-CSRF-Token'] = csrf;
  const response = await fetch(path, {...options, headers});
  if (!response.ok) throw new Error((await response.text()) || `Request failed (${response.status})`);
  return response.status === 204 ? null : response.json();
}

function message(id, text, error = false) {
  $(id).textContent = text;
  $(id).classList.toggle('error', error);
}

for (const name of ['title', 'description', 'location', 'organizer', 'attendee']) {
  const wrapper = document.createElement('fieldset');
  wrapper.innerHTML = `<legend>${name[0].toUpperCase() + name.slice(1)}</legend>
    <label>Value<input id="filter-${name}" placeholder="No filter"></label>
    <div class="two compact"><label>Match<select id="mode-${name}"><option value="contains">Contains</option><option value="exact">Exact</option><option value="regex">Regular expression</option></select></label>
    <label class="inline"><input id="case-${name}" type="checkbox"> Case-sensitive</label></div>`;
  $('textFilters').append(wrapper);
}

function criterion(name) {
  const value = $(`filter-${name}`).value;
  return value ? {value, mode: $(`mode-${name}`).value, case_sensitive: $(`case-${name}`).checked} : null;
}

function filterSpec() {
  const mode = document.querySelector('input[name="rangeMode"]:checked').value;
  const range = {mode, timezone: $('timezone').value || 'UTC', days_before: Number($('daysBefore').value), days_after: Number($('daysAfter').value)};
  if (mode === 'absolute') {
    range.start = $('rangeStart').value || null;
    range.end = $('rangeEnd').value || null;
  }
  return {
    calendar_ids: selected($('calendarIds')),
    date_range: range,
    title: criterion('title'), description: criterion('description'), location: criterion('location'),
    organizer: criterion('organizer'), attendee: criterion('attendee'),
    timing: $('timing').value, recurrence: $('recurrenceFilter').value,
    visibility: selected($('visibilityFilter')), event_types: selected($('eventTypes')),
  };
}

function editSpec() {
  const titleSet = $('titleSet').value;
  const titleFind = $('titleFind').value;
  return {
    title_set: titleSet === '' ? null : titleSet,
    title_find: titleFind === '' ? null : titleFind,
    title_replace: $('titleReplace').value,
    title_case_sensitive: $('titleCase').checked,
    description_mode: $('descriptionMode').value,
    description_value: $('descriptionValue').value,
    location_set: $('locationSet').value === '' ? null : $('locationSet').value,
    shift_minutes: nullableNumber('shiftMinutes'), duration_minutes: nullableNumber('durationMinutes'),
    duration_delta_minutes: nullableNumber('durationDelta'), visibility: $('visibility').value || null,
    replace_reminders: $('replaceReminders').checked, reminders: state.reminders,
    destination_calendar_id: $('destination').value || null, delete: $('deleteEvents').checked,
  };
}

function presetPayload() {
  return {name: $('presetName').value, filters: filterSpec(), edit: editSpec(), recurrence_mode: $('recurrenceMode').value, notifications: $('notifications').value};
}

async function refreshAuth() {
  const status = await api('/api/auth/status');
  $('connectionBadge').textContent = status.connected ? '● Google connected' : status.connecting ? 'Authorizing…' : 'Not connected';
  $('connectionBadge').classList.toggle('connected', status.connected);
  $('setupPanel').classList.toggle('hidden', status.connected);
  $('workspace').classList.toggle('hidden', !status.connected);
  $('connectButton').disabled = !status.client_configured || status.connecting;
  message('authMessage', status.error || (status.client_configured ? 'Desktop credentials are ready.' : ''), Boolean(status.error));
  if (status.connected && !state.loaded) {
    await Promise.all([loadCalendars(), loadPresets()]);
    state.loaded = true;
  }
  return status;
}

$('credentialFile').addEventListener('change', async event => {
  try {
    const file = event.target.files[0];
    if (!file) return;
    await api('/api/auth/import', {method: 'POST', body: JSON.stringify({credentials_json: await file.text()})});
    message('authMessage', 'Credentials imported. They remain on this computer.');
    await refreshAuth();
  } catch (error) { message('authMessage', error.message, true); }
});

$('connectButton').addEventListener('click', async () => {
  try {
    await api('/api/auth/connect', {method: 'POST'});
    const poll = setInterval(async () => {
      try { const status = await refreshAuth(); if (!status.connecting) clearInterval(poll); } catch (_) {}
    }, 1200);
  } catch (error) { message('authMessage', error.message, true); }
});

$('logoutButton').addEventListener('click', async () => {
  await api('/api/auth/logout', {method: 'POST'});
  state.loaded = false; state.preview = null;
  await refreshAuth();
});

async function loadCalendars() {
  state.calendars = await api('/api/calendars');
  $('calendarIds').innerHTML = state.calendars.map(c => `<option value="${escapeHtml(c.id)}" ${c.primary && c.writable ? 'selected' : ''} ${c.writable ? '' : 'disabled'}>${escapeHtml(c.name)}${c.writable ? '' : ' (read only)'}</option>`).join('');
  $('destination').innerHTML = '<option value="">Do not move</option>' + state.calendars.filter(c => c.writable).map(c => `<option value="${escapeHtml(c.id)}">${escapeHtml(c.name)}</option>`).join('');
  const primary = state.calendars.find(c => c.primary);
  if (primary) $('timezone').value = primary.timezone;
}

document.querySelectorAll('input[name="rangeMode"]').forEach(radio => radio.addEventListener('change', () => {
  const relative = document.querySelector('input[name="rangeMode"]:checked').value === 'relative';
  $('relativeRange').classList.toggle('hidden', !relative); $('absoluteRange').classList.toggle('hidden', relative);
}));

$('addReminder').addEventListener('click', () => {
  const reminder = {method: $('reminderMethod').value, minutes: Number($('reminderMinutes').value)};
  if (!Number.isInteger(reminder.minutes) || reminder.minutes < 0 || reminder.minutes > 40320 || state.reminders.length >= 5) return;
  state.reminders.push(reminder); $('replaceReminders').checked = true; renderReminders();
});

function renderReminders() {
  $('reminderList').innerHTML = state.reminders.map((r, index) => `<button class="chip" data-reminder="${index}" title="Remove">${r.method} · ${r.minutes} min ×</button>`).join('');
  document.querySelectorAll('[data-reminder]').forEach(button => button.onclick = () => { state.reminders.splice(Number(button.dataset.reminder), 1); renderReminders(); });
}

$('deleteEvents').addEventListener('change', () => {
  document.querySelectorAll('#workspace input:not(#deleteEvents), #workspace textarea, #workspace select').forEach(element => {
    if (!['calendarIds','notifications','recurrenceMode','recurrenceFilter','timing','timezone','daysBefore','daysAfter','rangeStart','rangeEnd','visibilityFilter','eventTypes','presetSelect'].includes(element.id) && !element.id.startsWith('filter-') && !element.id.startsWith('mode-') && !element.id.startsWith('case-')) element.disabled = $('deleteEvents').checked;
  });
});

$('previewButton').addEventListener('click', async () => {
  try {
    message('actionMessage', 'Searching calendars…');
    const payload = {filters: filterSpec(), recurrence_mode: $('recurrenceMode').value};
    state.preview = await api('/api/preview', {method: 'POST', body: JSON.stringify(payload)});
    renderPreview(); message('actionMessage', '');
  } catch (error) { message('actionMessage', error.message, true); }
});

function renderPreview() {
  const items = state.preview.items;
  $('previewPanel').classList.remove('hidden');
  $('previewSummary').textContent = `${items.length} event${items.length === 1 ? '' : 's'} matched`;
  $('previewWarnings').textContent = state.preview.warnings.join(' ');
  $('previewWarnings').classList.toggle('hidden', !state.preview.warnings.length);
  $('previewRows').innerHTML = items.map(item => `<tr><td><input class="event-check" type="checkbox" checked value="${escapeHtml(item.key)}"></td><td><strong>${escapeHtml(item.title)}</strong>${item.match_count > 1 ? `<br><small>${item.match_count} matching occurrences</small>` : ''}</td><td>${escapeHtml(formatTime(item.start))}</td><td>${escapeHtml(item.event_type)}${item.recurring ? ' · recurring' : ''}</td><td>${escapeHtml(item.location || '—')}</td><td>${item.move_eligible ? 'Eligible' : 'No'}</td></tr>`).join('');
  $('selectAll').checked = true;
  updateDeleteConfirmation();
  $('previewPanel').scrollIntoView({behavior: 'smooth'});
}

$('selectAll').addEventListener('change', () => document.querySelectorAll('.event-check').forEach(box => box.checked = $('selectAll').checked));
$('previewRows').addEventListener('change', updateDeleteConfirmation);
function selectedKeys() { return [...document.querySelectorAll('.event-check:checked')].map(box => box.value); }
function updateDeleteConfirmation() {
  const deleting = $('deleteEvents').checked;
  $('deleteConfirmWrap').classList.toggle('hidden', !deleting);
  $('deletePhrase').textContent = `DELETE ${selectedKeys().length}`;
}

$('applyButton').addEventListener('click', async () => {
  try {
    const keys = selectedKeys();
    if (!keys.length) throw new Error('Select at least one event.');
    const payload = {preview_token: state.preview.token, selected_keys: keys, edit: editSpec(), notifications: $('notifications').value, delete_confirmation: $('deleteConfirmation').value || null};
    $('applyButton').disabled = true; $('applyButton').textContent = 'Applying…';
    const response = await api('/api/apply', {method: 'POST', body: JSON.stringify(payload)});
    renderResults(response);
  } catch (error) { message('actionMessage', error.message, true); }
  finally { $('applyButton').disabled = false; $('applyButton').textContent = 'Apply to selected events'; }
});

function renderResults(response) {
  $('resultsPanel').classList.remove('hidden');
  $('results').innerHTML = response.results.map(result => `<div class="result"><span>${escapeHtml(result.title)} — ${escapeHtml(result.message)}</span><strong class="${result.status}">${result.status}</strong></div>`).join('');
  $('undoButton').classList.toggle('hidden', !response.undo_available);
  $('resultsPanel').scrollIntoView({behavior: 'smooth'});
}

$('undoButton').addEventListener('click', async () => {
  try { renderResults(await api('/api/undo', {method: 'POST', body: JSON.stringify({notifications: $('notifications').value})})); }
  catch (error) { message('actionMessage', error.message, true); }
});

async function loadPresets() {
  state.presets = await api('/api/presets');
  $('presetSelect').innerHTML = '<option value="">Choose a preset…</option>' + state.presets.map(p => `<option value="${p.id}">${escapeHtml(p.name)}</option>`).join('');
}

$('savePreset').addEventListener('click', async () => {
  try { await api('/api/presets', {method: 'POST', body: JSON.stringify(presetPayload())}); await loadPresets(); message('actionMessage', 'Preset saved.'); }
  catch (error) { message('actionMessage', error.message, true); }
});

$('deletePreset').addEventListener('click', async () => {
  const id = $('presetSelect').value; if (!id) return;
  await api(`/api/presets/${id}`, {method: 'DELETE'}); await loadPresets();
});

$('presetSelect').addEventListener('change', () => {
  const preset = state.presets.find(p => String(p.id) === $('presetSelect').value);
  if (preset) loadPreset(preset);
});

function loadPreset(preset) {
  $('presetName').value = preset.name;
  const f = preset.filters; selectValues($('calendarIds'), f.calendar_ids); $('timing').value = f.timing; $('recurrenceFilter').value = f.recurrence; $('recurrenceMode').value = preset.recurrence_mode;
  $('timezone').value = f.date_range.timezone; $('daysBefore').value = f.date_range.days_before; $('daysAfter').value = f.date_range.days_after;
  const rangeRadio = document.querySelector(`input[name="rangeMode"][value="${f.date_range.mode}"]`); rangeRadio.checked = true; rangeRadio.dispatchEvent(new Event('change'));
  $('rangeStart').value = localInput(f.date_range.start); $('rangeEnd').value = localInput(f.date_range.end);
  for (const name of ['title','description','location','organizer','attendee']) { const c = f[name]; $(`filter-${name}`).value = c?.value || ''; $(`mode-${name}`).value = c?.mode || 'contains'; $(`case-${name}`).checked = c?.case_sensitive || false; }
  selectValues($('visibilityFilter'), f.visibility); selectValues($('eventTypes'), f.event_types);
  const e = preset.edit; $('titleSet').value = e.title_set ?? ''; $('titleFind').value = e.title_find ?? ''; $('titleReplace').value = e.title_replace; $('titleCase').checked = e.title_case_sensitive;
  $('descriptionMode').value = e.description_mode; $('descriptionValue').value = e.description_value; $('locationSet').value = e.location_set ?? '';
  $('shiftMinutes').value = e.shift_minutes ?? ''; $('durationMinutes').value = e.duration_minutes ?? ''; $('durationDelta').value = e.duration_delta_minutes ?? ''; $('visibility').value = e.visibility ?? ''; $('destination').value = e.destination_calendar_id ?? '';
  $('replaceReminders').checked = e.replace_reminders; state.reminders = e.reminders || []; renderReminders(); $('deleteEvents').checked = e.delete; $('notifications').value = preset.notifications;
}

function selectValues(element, values) { [...element.options].forEach(option => option.selected = values.includes(option.value)); }
function localInput(value) { return value ? value.slice(0, 16) : ''; }
function formatTime(value) { if (!value) return '—'; const parsed = new Date(value); return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString(); }
function escapeHtml(value) { const div = document.createElement('div'); div.textContent = String(value); return div.innerHTML; }

refreshAuth().catch(error => { $('connectionBadge').textContent = 'Startup error'; message('authMessage', error.message, true); $('setupPanel').classList.remove('hidden'); });
