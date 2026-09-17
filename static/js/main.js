// ── Star field ────────────────────────────────────────
function drawStars() {
  const svg = document.querySelector('.stars');
  if (!svg) return;
  const w = window.innerWidth, h = window.innerHeight;
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  let html = '';
  for (let i = 0; i < 120; i++) {
    const x  = Math.random() * w;
    const y  = Math.random() * h;
    const r  = Math.random() * 1.2;
    const op = (Math.random() * 0.5 + 0.1).toFixed(2);
    html += `<circle cx="${x}" cy="${y}" r="${r}" fill="white" opacity="${op}"/>`;
  }
  svg.innerHTML = html;
}
drawStars();

// ── Airport autocomplete ──────────────────────────────
function setupAutocomplete(inputId, dropdownId) {
  const input    = document.getElementById(inputId);
  const dropdown = document.getElementById(dropdownId);
  if (!input || !dropdown) return;

  let timer;
  let activeIndex = -1;
  let results     = [];

  function close() {
    dropdown.style.display = 'none';
    activeIndex = -1;
  }

  function highlight(index) {
    const items = dropdown.querySelectorAll('.ac-item');
    items.forEach((el, i) => el.classList.toggle('ac-active', i === index));
    if (items[index]) items[index].scrollIntoView({ block: 'nearest' });
  }

  function renderResults(data) {
    results = data;
    if (!data.length) { close(); return; }
    dropdown.innerHTML = data.map((a, i) => `
      <div class="ac-item" data-index="${i}">
        <span class="ac-iata">${a.iata}</span>
        <span class="ac-info">${a.name}, ${a.city} <span class="ac-country">${a.country}</span></span>
      </div>
    `).join('');
    dropdown.style.display = 'block';
    activeIndex = -1;

    dropdown.querySelectorAll('.ac-item').forEach(el => {
      el.addEventListener('mousedown', e => {
        e.preventDefault();
        const idx = parseInt(el.dataset.index);
        pick(results[idx]);
      });
    });
  }

  function pick(airport) {
    input.value        = `${airport.iata} — ${airport.city}, ${airport.country}`;
    input.dataset.iata = airport.iata;
    input.classList.remove('ac-invalid');
    close();
  }

  function markInvalid() {
    input.dataset.iata = '';
    input.classList.add('ac-invalid');
    input.focus();
  }

  input.addEventListener('input', () => {
    clearTimeout(timer);
    delete input.dataset.iata;
    input.classList.remove('ac-invalid');
    lastSearchKey = '';
    const q = input.value.trim();
    if (q.length < 2) { close(); return; }

    dropdown.innerHTML = '<div class="ac-loading">Searching…</div>';
    dropdown.style.display = 'block';

    timer = setTimeout(async () => {
      try {
        const res  = await fetch(`/airports/search?q=${encodeURIComponent(q)}`);
        const data = await res.json();
        renderResults(data);
      } catch {
        close();
      }
    }, 220);
  });

  input.addEventListener('keydown', e => {
    const items = dropdown.querySelectorAll('.ac-item');
    if (!items.length) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      activeIndex = Math.min(activeIndex + 1, items.length - 1);
      highlight(activeIndex);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      activeIndex = Math.max(activeIndex - 1, 0);
      highlight(activeIndex);
    } else if (e.key === 'Enter' && activeIndex >= 0) {
      e.preventDefault();
      pick(results[activeIndex]);
    } else if (e.key === 'Escape') {
      close();
    }
  });

  function tryResolve() {
    if (input.dataset.iata) return true;
    if (!input.value.trim()) return false;

    const q = input.value.trim().toUpperCase();
    const exactIata = results.find(r => r.iata === q);
    if (exactIata) { pick(exactIata); return true; }
    if (results.length === 1) { pick(results[0]); return true; }
    markInvalid();
    return false;
  }

  input._tryResolve = tryResolve;

  input.addEventListener('blur', () => {
    setTimeout(() => {
      close();
      if (!input.dataset.iata) tryResolve();
    }, 150);
  });
}

setupAutocomplete('origin', 'origin-dropdown');
setupAutocomplete('destination', 'destination-dropdown');

// ── Search + Filter/Sort ──────────────────────────────
let allFlights    = [];
let paxCount      = 1;
let lastSearchKey = '';

async function searchFlights() {
  const originInput = document.getElementById('origin');
  const destInput   = document.getElementById('destination');
  const date        = document.getElementById('date').value;
  paxCount          = Math.max(1, parseInt(document.getElementById('passengers').value) || 1);
  const resultsEl   = document.getElementById('results');

  originInput?._tryResolve?.();
  destInput?._tryResolve?.();

  const origin      = originInput?.dataset.iata;
  const destination = destInput?.dataset.iata;

  if (!origin) {
    const msg = originInput?.value.trim()
      ? 'Please select an origin airport from the dropdown.'
      : 'Please enter an origin airport.';
    originInput?.classList.add('ac-invalid');
    showError(resultsEl, msg);
    originInput?.focus(); return;
  }
  if (!destination) {
    const msg = destInput?.value.trim()
      ? 'Please select a destination airport from the dropdown.'
      : 'Please enter a destination airport.';
    destInput?.classList.add('ac-invalid');
    showError(resultsEl, msg);
    destInput?.focus(); return;
  }

  const searchKey = `${origin}|${destination}|${date}|${paxCount}`;
  if (searchKey === lastSearchKey) return;
  lastSearchKey = searchKey;

  resultsEl.innerHTML = `<div class="state-empty">
    <div class="loading-dots"><span></span><span></span><span></span></div>
    <p>Searching flights…</p>
  </div>`;

  try {
    const res  = await fetch(`/search?origin=${origin}&destination=${destination}&date=${date}`);
    const data = await res.json();

    if (!res.ok)      { showError(resultsEl, data.error || 'Search failed.'); return; }
    if (!data.length) { showError(resultsEl, 'No flights found for that route.'); return; }

    allFlights = data;
    renderFiltersAndResults();
    document.getElementById('results').scrollIntoView({ behavior: 'smooth', block: 'start' });

  } catch (e) {
    lastSearchKey = '';
    showError(resultsEl, 'Something went wrong. Try again.');
  }
}

function renderFiltersAndResults() {
  const resultsEl = document.getElementById('results');
  const prices    = allFlights.map(f => f.price_usd * paxCount);
  const minPrice  = Math.floor(Math.min(...prices));
  const maxPrice  = Math.ceil(Math.max(...prices));
  const cabins    = [...new Set(allFlights.map(f => f.cabin))].sort();

  resultsEl.innerHTML = `
    <div class="filters-bar">
      <div class="filters-row">
        <div class="filter-group">
          <span class="filter-label">Sort</span>
          <div class="filter-pills" id="sort-pills">
            <button class="pill active" data-sort="price">Price</button>
            <button class="pill" data-sort="departure">Departure</button>
            <button class="pill" data-sort="duration">Duration</button>
          </div>
        </div>
        <div class="filter-group">
          <span class="filter-label">Cabin</span>
          <div class="filter-pills" id="cabin-pills">
            <button class="pill active" data-cabin="all">All</button>
            ${cabins.map(c => `<button class="pill" data-cabin="${c}">${c}</button>`).join('')}
          </div>
        </div>
        <div class="filter-group">
          <span class="filter-label">Departs</span>
          <div class="filter-pills" id="time-pills">
            <button class="pill active" data-time="any">Any</button>
            <button class="pill" data-time="morning">Morning</button>
            <button class="pill" data-time="afternoon">Afternoon</button>
            <button class="pill" data-time="evening">Evening</button>
          </div>
        </div>
        <div class="filter-group filter-group-price">
          <span class="filter-label">Max price <strong id="price-display">$${maxPrice.toLocaleString()}</strong></span>
          <input type="range" class="price-slider" id="price-slider"
            min="${minPrice}" max="${maxPrice}" value="${maxPrice}"
            oninput="onPriceSlide(this.value)">
        </div>
        <button class="filter-reset" onclick="resetFilters()">Reset</button>
      </div>
    </div>
    <div id="results-list"></div>
  `;

  document.getElementById('sort-pills').addEventListener('click', e => {
    const btn = e.target.closest('.pill[data-sort]');
    if (!btn) return;
    document.querySelectorAll('#sort-pills .pill').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    applyFilters();
  });

  document.getElementById('cabin-pills').addEventListener('click', e => {
    const btn = e.target.closest('.pill[data-cabin]');
    if (!btn) return;
    document.querySelectorAll('#cabin-pills .pill').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    applyFilters();
  });

  document.getElementById('time-pills').addEventListener('click', e => {
    const btn = e.target.closest('.pill[data-time]');
    if (!btn) return;
    document.querySelectorAll('#time-pills .pill').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    applyFilters();
  });

  applyFilters();
}

function onPriceSlide(val) {
  document.getElementById('price-display').textContent = '$' + parseInt(val).toLocaleString();
  applyFilters();
}

function resetFilters() {
  const prices   = allFlights.map(f => f.price_usd * paxCount);
  const maxPrice = Math.ceil(Math.max(...prices));
  const slider   = document.getElementById('price-slider');
  if (slider) {
    slider.value = maxPrice;
    document.getElementById('price-display').textContent = '$' + maxPrice.toLocaleString();
  }
  ['sort-pills','cabin-pills','time-pills'].forEach(id => {
    const first = document.querySelector('#' + id + ' .pill');
    if (first) {
      document.querySelectorAll('#' + id + ' .pill').forEach(p => p.classList.remove('active'));
      first.classList.add('active');
    }
  });
  applyFilters();
}

function applyFilters() {
  const sort  = document.querySelector('#sort-pills .pill.active')?.dataset.sort   || 'price';
  const cabin = document.querySelector('#cabin-pills .pill.active')?.dataset.cabin || 'all';
  const time  = document.querySelector('#time-pills .pill.active')?.dataset.time   || 'any';
  const maxPx = parseFloat(document.getElementById('price-slider')?.value) || Infinity;
  const list  = document.getElementById('results-list');
  if (!list) return;

  let filtered = allFlights.filter(f => {
    const total = f.price_usd * paxCount;
    if (total > maxPx) return false;
    if (cabin !== 'all' && f.cabin !== cabin) return false;
    if (time !== 'any') {
      const dep = f.departure.endsWith('Z') ? f.departure : f.departure + 'Z';
      const h = new Date(dep).getUTCHours();
      if (time === 'morning'   && !(h >= 5  && h < 12)) return false;
      if (time === 'afternoon' && !(h >= 12 && h < 18)) return false;
      if (time === 'evening'   && !(h >= 18 || h < 5))  return false;
    }
    return true;
  });

  filtered.sort((a, b) => {
    if (sort === 'price')     return a.price_usd - b.price_usd;
    if (sort === 'departure') return new Date(a.departure + (a.departure.endsWith('Z') ? '' : 'Z')) - new Date(b.departure + (b.departure.endsWith('Z') ? '' : 'Z'));
    if (sort === 'duration')  return (new Date(a.arrival) - new Date(a.departure)) - (new Date(b.arrival) - new Date(b.departure));
    return 0;
  });

  if (!filtered.length) {
    list.innerHTML = `<div class="state-empty"><p>No flights match your filters. <button class="link-btn" onclick="resetFilters()">Clear filters</button></p></div>`;
    return;
  }

  list.innerHTML = `<p class="results-header">${filtered.length} of ${allFlights.length} flight${allFlights.length > 1 ? 's' : ''}</p>`;
  filtered.forEach(f => list.appendChild(flightCard(f, paxCount)));
}

function flightCard(f, passengers) {
  const dep      = new Date(f.departure + (f.departure.endsWith('Z') ? '' : 'Z'));
  const arr      = new Date(f.arrival   + (f.arrival.endsWith('Z')   ? '' : 'Z'));
  const dur      = duration(dep, arr);
  const total    = (f.price_usd * passengers).toLocaleString();
  const seatsLow = f.seats > 0 && f.seats <= 5;
  const card     = document.createElement('div');
  card.className = 'flight-card';
  card.innerHTML = `
    <div>
      <div class="flight-code">${f.origin}</div>
      <div class="flight-time">${fmt(dep)}</div>
      <div class="flight-city">${f.origin_city}</div>
    </div>
    <div class="flight-route">
      <div class="route-line"></div>
      <div class="flight-duration">${dur}</div>
    </div>
    <div>
      <div class="flight-code">${f.destination}</div>
      <div class="flight-time">${fmt(arr)}</div>
      <div class="flight-city">${f.dest_city}</div>
    </div>
    <div class="flight-price">
      <div class="price-label">from</div>
      <div class="price-usd">$${total}</div>
      <div class="flight-meta">
        <span class="cabin-badge">${f.cabin}</span>
        ${seatsLow ? `<span class="seats-warn">${f.seats} left</span>` : ''}
      </div>
      <button class="btn-book" onclick="bookFlight('${f.id}', ${passengers})">Select</button>
    </div>
  `;
  return card;
}

async function bookFlight(flightId, passengers) {
  const res  = await fetch(`/book/${flightId}`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ passengers: parseInt(passengers) })
  });
  const data = await res.json();
  if (res.status === 401) { window.location.href = '/login'; return; }
  if (!res.ok) { alert(data.error); return; }
  window.location.href = `/extras/${flightId}?passengers=${passengers}`;
}

function fmt(d) {
  return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
}

function duration(dep, arr) {
  const diff = Math.abs(arr - dep);
  const h    = Math.floor(diff / 36e5);
  const m    = Math.floor((diff % 36e5) / 6e4);
  return `${h}h ${m}m`;
}

function showError(el, msg) {
  el.innerHTML = `<div class="state-empty"><p>${msg}</p></div>`;
}

// ── Auth ──────────────────────────────────────────────
async function login() {
  const email    = document.getElementById('email').value.trim();
  const password = document.getElementById('password').value;
  const err      = document.getElementById('auth-error');

  if (!email || !password) { showAuthError(err, 'Fill in all fields.'); return; }

  const res  = await fetch('/login', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ email, password })
  });
  const data = await res.json();

  if (!res.ok) { showAuthError(err, data.error); return; }
  window.location.href = '/';
}

async function register() {
  const full_name = document.getElementById('full_name').value.trim();
  const email     = document.getElementById('email').value.trim();
  const password  = document.getElementById('password').value;
  const err       = document.getElementById('auth-error');

  if (!full_name || !email || !password) { showAuthError(err, 'Fill in all fields.'); return; }
  if (password.length < 6) { showAuthError(err, 'Password must be at least 6 characters.'); return; }

  const res  = await fetch('/register', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ full_name, email, password })
  });
  const data = await res.json();

  if (!res.ok) { showAuthError(err, data.error); return; }
  window.location.href = '/login';
}

function showAuthError(el, msg) {
  if (!el) return;
  el.textContent = msg;
  el.classList.add('show');
}

// ── Extras ────────────────────────────────────────────
const extraSelections = {};
let baseFare       = 0;
let passengerCount = 1;

function selectExtra(el, key) {
  document.querySelectorAll(`.extra-option[data-key="${key}"]`).forEach(o => {
    o.classList.remove('selected');
  });
  el.classList.add('selected');
  extraSelections[key] = parseFloat(el.dataset.price);
  updateExtrasTotal();
}

function updateExtrasTotal() {
  const extrasTotal = Object.values(extraSelections).reduce((a, b) => a + b, 0);
  const total       = baseFare + (extrasTotal * passengerCount);
  const el          = document.getElementById('extras-total');
  if (el) el.textContent = `$${total.toFixed(2)}`;
}

function continueToPassengers(flightId, passengers) {
  const extrasTotal = Object.values(extraSelections).reduce((a, b) => a + b, 0);
  const extrasCost  = (extrasTotal * passengers).toFixed(2);
  window.location.href = `/passengers/${flightId}?passengers=${passengers}&extras_cost=${extrasCost}`;
}

(function initExtras() {
  const totalEl = document.getElementById('extras-total');
  if (!totalEl) return;
  baseFare       = parseFloat(totalEl.textContent.replace('$', '')) || 0;
  passengerCount = parseInt(document.querySelector('.extras-sub')?.textContent.match(/\d+/)?.[0]) || 1;
  document.querySelectorAll('.extras-section').forEach(section => {
    const first = section.querySelector('.extra-option');
    if (first) {
      first.classList.add('selected');
      const key        = first.dataset.key;
      extraSelections[key] = parseFloat(first.dataset.price);
    }
  });
})();

// ── Payment ───────────────────────────────────────────
const RATES = {
  BTC:  0.000015,
  ETH:  0.00035,
  SOL:  0.065,
  USDT: 1.0,
  USDC: 1.0,
};

// selectedCrypto and selectedChain are declared in payment.html to avoid scope conflicts

function copyAddress(elemId, btn) {
  const text = document.getElementById(elemId)?.textContent?.trim();
  if (!text || text === 'Not configured') return;
  navigator.clipboard.writeText(text).then(() => {
    btn.classList.add('copied');
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg> Copied!`;
    setTimeout(() => {
      btn.classList.remove('copied');
      btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Copy`;
    }, 2000);
  });
}

// selectCrypto is defined in payment.html

async function confirmPayment(bookingId) {
  const txHash = document.getElementById('tx-hash')?.value.trim();
  const err    = document.getElementById('pay-error');
  const btn    = document.getElementById('btn-confirm');

  // selectedCrypto and selectedChain are declared as var in payment.html (window scope)
  const crypto = window.selectedCrypto;
  const chain  = window.selectedChain;

  if (!crypto)  { showAuthError(err, 'Select a payment method.'); return; }
  if (!txHash)  { showAuthError(err, 'Paste your transaction hash.'); return; }

  const needsChain = (crypto === 'USDT' || crypto === 'USDC');
  if (needsChain && !chain) {
    showAuthError(err, 'Please select a network (Ethereum or Solana).');
    return;
  }

  // Disable button immediately — prevents double-submit
  btn.disabled    = true;
  btn.textContent = 'Submitting…';
  if (err) err.style.display = 'none';

  const RATES = { BTC: 0.000015, ETH: 0.00035, SOL: 0.065, USDT: 1.0, USDC: 1.0 };
  const totalEl  = document.querySelector('.summary-row.total .summary-val');
  const totalUsd = totalEl ? parseFloat(totalEl.textContent.replace('$', '')) : 0;
  const decimals = (crypto === 'USDT' || crypto === 'USDC') ? 2 : 6;
  const amount   = (totalUsd * RATES[crypto]).toFixed(decimals);

  try {
    const res  = await fetch(`/pay/${bookingId}/submit`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({
        crypto_type:   crypto,
        chain:         chain,
        tx_hash:       txHash,
        amount_crypto: parseFloat(amount)
      })
    });
    const data = await res.json();

    if (!res.ok) {
      showAuthError(err, data.error || 'Payment failed.');
      btn.disabled    = false;
      btn.textContent = 'Confirm payment';
      return;
    }
    window.location.href = data.pending_url || `/booking/${bookingId}/pending`;
  } catch (e) {
    showAuthError(err, 'Network error — please try again.');
    btn.disabled    = false;
    btn.textContent = 'Confirm payment';
  }
}


async function cancelBooking(bookingId) {
  if (!confirm('Cancel this booking? This cannot be undone.')) return;

  const res  = await fetch(`/booking/${bookingId}/cancel`, { method: 'POST' });
  const data = await res.json();

  if (!res.ok) { alert(data.error || 'Could not cancel booking.'); return; }

  const card = document.getElementById(`booking-${bookingId}`);
  if (!card) { location.reload(); return; }

  card.classList.add('booking-cancelled');
  const statusEl = card.querySelector('.bk-status');
  if (statusEl) {
    statusEl.className   = 'bk-status bk-status-cancelled';
    statusEl.textContent = 'Cancelled';
  }
  const actions = card.querySelector('.bk-status-row');
  if (actions) {
    actions.querySelectorAll('.bk-action-link, .bk-cancel-btn').forEach(el => el.remove());
  }
}

// ── Passenger details ─────────────────────────────────
async function submitPassengers(flightId, passengers) {
  const err = document.getElementById('pax-error');

  const firstNames = [...document.querySelectorAll('.pax-first')].map(el => el.value.trim());
  const lastNames  = [...document.querySelectorAll('.pax-last')].map(el => el.value.trim());
  const passports  = [...document.querySelectorAll('.pax-passport')].map(el => el.value.trim());
  const email      = document.getElementById('contact-email')?.value.trim();
  const phone      = document.getElementById('contact-phone')?.value.trim();

  for (let i = 0; i < passengers; i++) {
    if (!firstNames[i] || !lastNames[i]) {
      showAuthError(err, `Enter the full name for passenger ${i + 1}.`); return;
    }
    if (!passports[i]) {
      showAuthError(err, `Enter the passport number for passenger ${i + 1}.`); return;
    }
  }

  if (!email) { showAuthError(err, 'Enter a contact email address.'); return; }

  const extrasParam = new URLSearchParams(window.location.search).get('extras_cost') || '0';

  // ── KEY FIX: pass passengers count in the query string so app.py reads it correctly ──
  const res = await fetch(`/passengers/${flightId}?passengers=${passengers}&extras_cost=${extrasParam}`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({
      contact_email:   email,
      contact_phone:   phone,
      passenger_names: firstNames.map((fn, i) => `${fn} ${lastNames[i]}`)
    })
  });

  const data = await res.json();
  if (!res.ok) { showAuthError(err, data.error || 'Something went wrong.'); return; }
  window.location.href = `/pay/${data.booking_id}`;
}
