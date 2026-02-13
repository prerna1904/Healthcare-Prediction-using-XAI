// Modern dynamic front-end for Hospital Scheduler
// Compatible with API endpoints: /api/doctors, /api/slots/:id, /api/appointments

const POLL_INTERVAL = 6000; // ms
const doctorSelect = document.getElementById('doctorSelect');
const doctorsList = document.getElementById('doctorsList');
const specialtyFilter = document.getElementById('specialtyFilter');
const searchBox = document.getElementById('searchBox');
const slotSelect = document.getElementById('slotSelect');
const slotSelectWrap = document.getElementById('slotSelectWrap');
const patientInput = document.getElementById('patient');
const isEmergency = document.getElementById('isEmergency');
const bookBtn = document.getElementById('bookBtn');
const msg = document.getElementById('msg');
const appointmentsList = document.getElementById('appointmentsList');
const slotsGrid = document.getElementById('slotsGrid');
const refreshBtn = document.getElementById('refreshBtn');
const doctorHandling = document.getElementById('doctorHandling');
const emergencyModal = new bootstrap.Modal(document.getElementById('emergencyModal'), {});

let doctorsCache = [];
let apptsCache = [];

async function fetchJSON(url, opts) {
  try {
    const res = await fetch(url, opts);
    return await res.json();
  } catch (e) {
    console.error('fetch error', e);
    return null;
  }
}

// Live IST clock
function startClock() {
  function pad(n){ return n.toString().padStart(2,'0'); }
  setInterval(()=> {
    const now = new Date();
    // convert to IST by adding offset (UTC +5:30)
    const utc = now.getTime() + now.getTimezoneOffset()*60000;
    const istOffset = 5.5 * 3600000;
    const ist = new Date(utc + istOffset);
    const hh = pad(ist.getHours()), mm = pad(ist.getMinutes()), ss = pad(ist.getSeconds());
    document.getElementById('istClock').textContent = `IST — ${hh}:${mm}:${ss}`;
  }, 1000);
}

// Load doctors and populate UI
async function loadDoctors() {
  const docs = await fetchJSON('/api/doctors');
  if (!docs) return;
  doctorsCache = docs;
  populateSpecialtyFilter(docs);
  renderDoctorsList(docs);
  fillDoctorSelect(docs);
  updateDoctorHandlingUI();
  // if doctor selected, load their slots
  const selected = doctorSelect.value || (docs[0] && docs[0].id);
  if (selected) {
    doctorSelect.value = selected;
    loadSlots(selected);
  }
}

function populateSpecialtyFilter(docs) {
  const specs = Array.from(new Set(docs.map(d => d.specialty).filter(Boolean))).sort();
  // clear and add
  specialtyFilter.innerHTML = '<option value="">All specialties</option>';
  specs.forEach(s => {
    const o = document.createElement('option'); o.value = s; o.textContent = s; specialtyFilter.appendChild(o);
  });
}

function renderDoctorsList(docs) {
  doctorsList.innerHTML = '';
  const q = searchBox.value.trim().toLowerCase();
  const specFilter = specialtyFilter.value;
  docs
    .filter(d => (!specFilter || d.specialty === specFilter))
    .filter(d => (!q || `${d.name} ${d.specialty}`.toLowerCase().includes(q)))
    .forEach(d => {
      const el = document.createElement('div'); el.className = 'doctor-card';
      el.innerHTML = `
        <div class="doc-avatar">${initials(d.name)}</div>
        <div class="doc-info">
          <div class="doc-name">${escapeHtml(d.name)} ${d.handling_emergency ? '<span class="handling">⚠️ Handling EM</span>' : ''}</div>
          <div class="doc-spec">${escapeHtml(d.specialty)}</div>
          <div class="load-bar" title="Recent emergency load"><i style="width:${Math.min(100,(d.handling_emergency? 70: 8))}%"></i></div>
        </div>
        <div>
          <button class="btn btn-sm btn-outline-primary select-doc" data-id="${d.id}"><i class="bi bi-arrow-right"></i></button>
        </div>
      `;
      doctorsList.appendChild(el);
    });

  // wire up select buttons
  Array.from(document.getElementsByClassName('select-doc')).forEach(b=>{
    b.onclick = () => {
      const id = b.getAttribute('data-id');
      doctorSelect.value = id;
      loadSlots(id);
      updateDoctorHandlingUI();
      scrollToElement(slotSelectWrap);
    };
  });
}

function fillDoctorSelect(docs) {
  // keep current selection
  const cur = doctorSelect.value;
  doctorSelect.innerHTML = '<option value="">-- Choose doctor (optional) --</option>';
  docs.forEach(d => {
    const o = document.createElement('option'); o.value = d.id; o.textContent = `${d.name} — ${d.specialty}`; doctorSelect.appendChild(o);
  });
  if (cur) doctorSelect.value = cur;
}

function updateDoctorHandlingUI() {
  const sel = doctorSelect.value ? parseInt(doctorSelect.value) : null;
  const d = doctorsCache.find(x => x.id === sel);
  if (d && d.handling_emergency) doctorHandling.innerHTML = `<span class="handling">⚠️ ${d.name} is currently handling an emergency</span>`;
  else doctorHandling.innerHTML = '';
}

// load slots for doctor id
async function loadSlots(doctorId) {
  if (!doctorId) {
    slotSelect.innerHTML = '<option value="">-- Select doctor first --</option>';
    slotsGrid.innerHTML = '';
    return;
  }
  const payload = await fetchJSON(`/api/slots/${doctorId}`);
  // server returns { doctor_handling_emergency: bool, slots: [] } in newer backend
  const slots = (payload && payload.slots) ? payload.slots : (payload || []);
  slotSelect.innerHTML = '<option value="">-- Choose pre-made slot (normal booking) --</option>';
  slots.forEach(s => {
    const opt = document.createElement('option'); opt.value = s.slot_id;
    const statusText = s.booked ? (s.emergency ? ' (EMERGENCY)' : ' (Booked)') : ' (Available)';
    opt.textContent = `${s.date} ${s.time}${statusText}`; slotSelect.appendChild(opt);
  });

  // render grid
  slotsGrid.innerHTML = '';
  slots.forEach(s => {
    const col = document.createElement('div'); col.className = 'col';
    const tile = document.createElement('div'); 
    const cls = s.emergency ? 'slot-tile emer' : (s.booked ? 'slot-tile booked' : 'slot-tile available');
    tile.className = cls;
    tile.innerHTML = `<div><div class="slot-time">${s.date} ${s.time}</div><div class="slot-status">${s.booked ? (s.emergency ? 'Emergency present' : 'Booked') : 'Available'}</div></div>
                      <div><button class="btn btn-sm ${s.booked ? 'btn-outline-secondary' : 'btn-outline-success'} slot-action" data-id="${s.slot_id}">${s.booked ? '<i class="bi bi-x-circle"></i>' : '<i class="bi bi-calendar-plus"></i>'}</button></div>`;
    col.appendChild(tile); slotsGrid.appendChild(col);
  });

  // wire tile action buttons (helpful quick-book only if available)
  Array.from(document.getElementsByClassName('slot-action')).forEach(btn=>{
    btn.onclick = () => {
      const id = parseInt(btn.getAttribute('data-id'));
      slotSelect.value = id;
      scrollToElement(bookBtn);
    };
  });
}

// load appointments
async function loadAppointments() {
  const appts = await fetchJSON('/api/appointments');
  if (!appts) return;
  apptsCache = appts;
  appointmentsList.innerHTML = '';
  appts.forEach(a => {
    const row = document.createElement('div');
    row.className = 'appt-row ' + (a.emergency==1 ? 'emergency' : 'normal');
    row.innerHTML = `
      <div>
        <div style="font-weight:700">${escapeHtml(a.patient)} ${a.emergency==1 ? '<span class="emergency-badge ms-2">EMERGENCY</span>' : ''}</div>
        <div class="small-muted">${escapeHtml(a.date||'')}${a.time ? ' ' + escapeHtml(a.time) : ''} — ${escapeHtml(a.doctor_name || 'N/A')}</div>
        <div class="small-muted">Assigned (IST): ${escapeHtml(a.created_at_ist || '')}</div>
      </div>
      <div style="min-width:130px; text-align:right">
        <button class="btn btn-sm btn-outline-danger cancel-appt" data-id="${a.id}"><i class="bi bi-trash"></i> Cancel</button>
      </div>
    `;
    appointmentsList.appendChild(row);
  });

  // wire cancel buttons
  Array.from(document.getElementsByClassName('cancel-appt')).forEach(b=>{
    b.onclick = async () => {
      const id = b.getAttribute('data-id');
      if (!confirm('Cancel appointment?')) return;
      const r = await fetch(`/api/appointments/${id}`, { method: 'DELETE' });
      if (r.ok) {
        showMsg('Appointment canceled', 'success');
        loadAppointments(); loadDoctors(); // refresh
      } else {
        const j = await r.json(); showMsg(j.error || 'Failed to cancel', 'danger');
      }
    };
  });
}

// booking
bookBtn.onclick = async () => {
  const patient = patientInput.value.trim();
  const doctor_id = doctorSelect.value ? parseInt(doctorSelect.value) : null;
  const slot_id = slotSelect.value ? parseInt(slotSelect.value) : null;
  const emergency = isEmergency.checked;

  if (!patient) return showMsg('Please enter patient name', 'danger');
  if (!emergency && (!doctor_id || !slot_id)) return showMsg('Normal booking requires doctor + slot', 'danger');

  const payload = { patient, emergency };
  if (doctor_id) payload.doctor_id = doctor_id;
  if (slot_id) payload.slot_id = slot_id;

  const res = await fetch('/api/appointments', {
    method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)
  });

  if (res.status === 201) {
    const j = await res.json();
    showMsg('Appointment booked', 'success');
    patientInput.value = ''; slotSelect.value = ''; isEmergency.checked = false;
    // If emergency: show modal with assigned doctor/time and refresh doctors list
    if (j.emergency == 1) {
      const body = document.getElementById('emergencyModalBody');
      body.innerHTML = `<div style="font-weight:700">Assigned: ${escapeHtml(j.doctor_name || 'N/A')}</div>
                        <div class="small-muted">Patient: ${escapeHtml(j.patient)}</div>
                        <div class="small-muted">Assigned at (IST): ${escapeHtml(j.date)} ${escapeHtml(j.time)}</div>`;
      emergencyModal.show();
    }
    // refresh
    await Promise.all([loadAppointments(), loadDoctors()]);
  } else {
    const j = await res.json();
    showMsg(j.error || 'Booking failed', 'danger');
    await loadSlots(doctor_id);
  }
};

// helpers
function showMsg(t, type='muted') {
  msg.textContent = t;
  msg.className = type === 'success' ? 'text-success' : (type === 'danger' ? 'text-danger' : 'text-muted');
  setTimeout(()=> { msg.textContent=''; msg.className='text-muted'; }, 3500);
}
function initials(name='') {
  return name.split(' ').map(n=>n[0]).slice(0,2).join('').toUpperCase();
}
function escapeHtml(s='') { return (s==null)?'':String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function scrollToElement(el) { el.scrollIntoView({ behavior:'smooth', block:'center' }); }

// refresh handlers
refreshBtn.onclick = () => { loadAll(); };

async function loadAll() {
  await Promise.all([loadDoctors(), loadAppointments()]);
}

startClock();
loadAll();
// auto-refresh periodically (doctors + appointments)
setInterval(loadAll, POLL_INTERVAL);

// small UI interactions
searchBox.oninput = () => renderDoctorsList(doctorsCache);
specialtyFilter.onchange = () => renderDoctorsList(doctorsCache);
doctorSelect.onchange = () => { loadSlots(doctorSelect.value); updateDoctorHandlingUI(); };
