// Petites salles IDF — interactive map
const map = L.map('map').setView([48.86, 2.35], 10);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap contributors', maxZoom: 19
}).addTo(map);

let group = L.layerGroup().addTo(map);
let data, dept = 'all', cat = 'all', priceMin = 0, priceMax = 100, capMin = 1, capMax = 20, searchQ = '';

// Keep the map focused on Île-de-France. Some scraped/geocoded rows resolve to
// homonymous towns outside IDF (Saint-Denis, Vincennes, etc.), which otherwise
// makes fitBounds zoom out to France and visually collapses the Paris cluster.
const IDF_BBOX = { minLat: 48.1, maxLat: 49.1, minLon: 1.4, maxLon: 3.6 };
function isInsideIdf(lat, lon) {
  return lat >= IDF_BBOX.minLat && lat <= IDF_BBOX.maxLat && lon >= IDF_BBOX.minLon && lon <= IDF_BBOX.maxLon;
}

function fitColor(s) {
  if (s >= 85) return '#0a7';
  if (s >= 70) return '#8bc34a';
  if (s >= 55) return '#ffc107';
  return '#ff7043';
}

function priceLabel(s) {
  if (s >= 85) return 'Gratuit / très cheap';
  if (s >= 70) return 'Bon prix';
  if (s >= 55) return 'Prix moyen';
  return 'Plus cher';
}

function esc(s) { return (s||'').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

function popupHTML(p) {
  const score = +p.fit_score || 0;
  const pScore = +p.price_score || 0;
  let html = `<div class="popup">
    <h3>${esc(p.name)}</h3>
    <span class="tag">${esc(p.department)}</span>
    <span class="tag">${esc(p.category)}</span>
    <span class="tag">fit ${score}</span>
    <span class="tag">${priceLabel(pScore)}</span>
    <div class="info-row"><b>Capacité</b> ${esc(p.capacity_text||'—')}</div>
    <div class="info-row"><b>Prix</b> ${esc(p.price_text||'à confirmer')}</div>
    <div class="info-row"><b>Adresse</b> ${esc(p.address||'—')}</div>`;
  if (p.contact) html += `<div class="info-row"><b>Contact</b> ${esc(p.contact)}</div>`;
  if (p.pros) html += `<div class="info-row pro"><b>Pros</b> ${esc(p.pros)}</div>`;
  if (p.cons) html += `<div class="info-row con"><b>Cons</b> ${esc(p.cons)}</div>`;
  html += `<div class="score-bar"><div class="score-fill" style="width:${score}%;background:${fitColor(score)}"></div></div>`;
  if (p.website) html += `<div style="margin-top:4px"><a href="${esc(p.website)}" target="_blank" rel="noopener">Site</a>`;
  if (p.source_url) html += ` · <a href="${esc(p.source_url)}" target="_blank" rel="noopener">Source</a>`;
  html += `</div></div>`;
  return html;
}

function jitteredLatLon(lat, lon, index, total) {
  if (total <= 1) return [lat, lon];
  // Spread same-coordinate venues in a small deterministic spiral.
  // 0.00008° ≈ 9m latitude in IDF; rings stay close enough to preserve location semantics.
  const angle = (index * 137.508) * Math.PI / 180; // golden angle
  const ring = Math.floor(index / 12) + 1;
  const radius = 0.00008 * ring;
  const dLat = Math.sin(angle) * radius;
  const dLon = Math.cos(angle) * radius / Math.cos(lat * Math.PI / 180);
  return [lat + dLat, lon + dLon];
}

function filteredFeatures() {
  return data.features.filter(f => {
    const p = f.properties;
    if (dept !== 'all' && p.department !== dept) return false;
    if (cat !== 'all' && (p.category||'').toLowerCase() !== cat) return false;
    const ps = +(p.price_score||0);
    if (ps < priceMin || ps > priceMax) return false;
    const cm = +(p.capacity_max_detected||0) || 999;
    if (cm < capMin || cm > capMax) return false;
    if (searchQ && !(p.name||'').toLowerCase().includes(searchQ) && !(p.city||'').toLowerCase().includes(searchQ) && !(p.category||'').toLowerCase().includes(searchQ)) return false;
    const coords = f.geometry && f.geometry.coordinates;
    if (!coords || coords.length < 2) return false;
    const [lon, lat] = coords;
    return Number.isFinite(+lat) && Number.isFinite(+lon) && isInsideIdf(+lat, +lon);
  });
}

function render() {
  group.clearLayers();
  const features = filteredFeatures();
  const buckets = new Map();
  features.forEach(f => {
    const [lon, lat] = f.geometry.coordinates;
    const key = `${(+lat).toFixed(6)},${(+lon).toFixed(6)}`;
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(f);
  });

  let n = 0;
  let uniquePoints = 0;
  for (const bucket of buckets.values()) {
    uniquePoints++;
    bucket.forEach((f, idx) => {
      const p = f.properties;
      const [lon, lat] = f.geometry.coordinates;
      const [jLat, jLon] = jitteredLatLon(+lat, +lon, idx, bucket.length);
      n++;
      L.circleMarker([jLat, jLon], {
        radius: bucket.length > 1 ? 6 : 7,
        color: bucket.length > 1 ? '#111' : '#222',
        weight: 1,
        fillColor: fitColor(+p.fit_score),
        fillOpacity: .85
      }).addTo(group).bindPopup(popupHTML(p) + (bucket.length > 1 ? `<div class="overlap-note">Point décalé : ${bucket.length} salles avaient la même coordonnée.</div>` : ''));
    });
  }
  document.getElementById('count').textContent = `${n} (${uniquePoints} points)`;
}
// Build category filters dynamically
function buildCatFilters() {
  const cats = new Set();
  data.features.forEach(f => { if (f.properties.category) cats.add(f.properties.category.toLowerCase()); });
  const cont = document.getElementById('cat-filters');
  const sorted = [...cats].sort();
  sorted.forEach(c => {
    const btn = document.createElement('button');
    btn.dataset.cat = c;
    btn.textContent = c.charAt(0).toUpperCase() + c.slice(1);
    btn.onclick = () => {
      cont.querySelectorAll('button').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      cat = c;
      render();
    };
    cont.appendChild(btn);
  });
}

// Dept filters
document.querySelectorAll('#dept-filters button').forEach(b => {
  b.onclick = () => {
    document.querySelectorAll('#dept-filters button').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    dept = b.dataset.d;
    render();
  };
});

// Sliders
document.getElementById('price-min').oninput = e => { priceMin = +e.target.value; document.getElementById('price-val').textContent = `${priceMin}–${priceMax}`; render(); };
document.getElementById('price-max').oninput = e => { priceMax = +e.target.value; document.getElementById('price-val').textContent = `${priceMin}–${priceMax}`; render(); };
document.getElementById('cap-min').oninput = e => { capMin = +e.target.value; document.getElementById('cap-val').textContent = `${capMin}–${capMax}`; render(); };
document.getElementById('cap-max').oninput = e => { capMax = +e.target.value; document.getElementById('cap-val').textContent = `${capMin}–${capMax}`; render(); };

// Search
document.getElementById('search').oninput = e => { searchQ = e.target.value.toLowerCase(); render(); };

// Mobile panel toggle
document.getElementById('close-panel').onclick = () => {
  document.getElementById('panel').classList.toggle('collapsed');
};
// Reopen on map click
map.on('click', () => {
  const panel = document.getElementById('panel');
  if (panel.classList.contains('collapsed')) panel.classList.remove('collapsed');
});

// Load data
fetch('salles_all_idf.geojson').then(r => r.json()).then(j => {
  data = j;
  buildCatFilters();
  render();
  map.fitBounds(group.getBounds().pad(0.05));
});