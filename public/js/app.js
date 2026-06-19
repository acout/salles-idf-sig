/* ===== App: Leaflet map + filters ===== */
(function () {
  'use strict';

  /* --- Map init --- */
  const map = L.map('map').setView([48.8566, 2.3522], 10);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 18
  }).addTo(map);

  let markers = L.layerGroup().addTo(map);
  let geojson = null;
  let currentDept = 'all';
  let currentCat = 'all';
  let priceMin = 0;
  let priceMax = 100;
  let capMin = 1;
  let capMax = 20;

  /* --- Color mapping for fit_score --- */
  function fitColor(score) {
    if (score >= 90) return '#0a7';
    if (score >= 80) return '#2ecc71';
    if (score >= 70) return '#8bc34a';
    if (score >= 60) return '#ffc107';
    if (score >= 50) return '#ff9800';
    return '#ff7043';
  }

  /* --- Price score color --- */
  function priceColor(score) {
    if (score >= 90) return '#d4edda';
    if (score >= 75) return '#c3e6cb';
    if (score >= 60) return '#fff3cd';
    return '#ffeeba';
  }

  /* --- Build category filter buttons from data --- */
  function buildCatFilters(features) {
    const cats = new Set();
    features.forEach(f => {
      const cat = f.properties.category;
      if (cat) cats.add(cat.split('/')[0].trim().toLowerCase());
    });
    const catNames = new Set();
    features.forEach(f => {
      const cat = f.properties.category;
      if (cat) catNames.add(cat);
    });
    const container = document.getElementById('cat-filters');
    // Keep "Tous" button
    catNames.forEach(cat => {
      const btn = document.createElement('button');
      btn.dataset.cat = cat;
      btn.textContent = cat;
      container.appendChild(btn);
    });
  }

  /* --- Popup HTML --- */
  function popupContent(p) {
    const priceText = p.price_text ? p.price_text : 'Non publié';
    const contactText = p.contact ? p.contact : 'À compléter';
    const websiteLink = p.website ? `<a href="${p.website}" target="_blank" rel="noopener">Site web</a>` : '';
    const sourceLink = p.source_url ? `<a href="${p.source_url}" target="_blank" rel="noopener">Source</a>` : '';
    const capMax = p.capacity_max_detected || '?';

    return `<div class="popup">
      <h3>${p.name}</h3>
      <div class="popup-meta">
        <span class="tag dept">${p.department} — ${p.city}</span>
        <span class="tag cat">${p.category}</span>
        <span class="tag fit">fit ${p.fit_score}/100</span>
        ${p.price_score ? `<span class="tag price">prix ${p.price_score}/100</span>` : ''}
        <span class="tag cap">${capMax} pers max</span>
      </div>
      <p><b>Adresse</b> : ${p.address}</p>
      <p><b>Capacité</b> : ${p.capacity_text}</p>
      <p><b>Tarif</b> : ${priceText}</p>
      <p><b>Contact</b> : ${contactText}</p>
      <p class="pros">👍 ${p.pros}</p>
      <p class="cons">⚠️ ${p.cons}</p>
      <div class="links">${websiteLink} ${sourceLink}</div>
    </div>`;
  }

  /* --- Render markers based on current filters --- */
  function render() {
    markers.clearLayers();
    let shown = 0;

    geojson.features.forEach(f => {
      const p = f.properties;
      // Department filter
      if (currentDept !== 'all' && p.department !== currentDept) return;
      // Category filter
      if (currentCat !== 'all' && p.category !== currentCat) return;
      // Price score filter
      if (p.price_score < priceMin || p.price_score > priceMax) return;
      // Capacity filter
      const cap = p.capacity_max_detected || 0;
      if (cap < capMin || cap > capMax) return;

      shown++;
      const marker = L.circleMarker([p.lat, p.lon], {
        radius: 9,
        color: '#222',
        weight: 1.5,
        fillColor: fitColor(+p.fit_score),
        fillOpacity: 0.88
      }).addTo(markers);
      marker.bindPopup(popupContent(p), { maxWidth: 340 });
    });

    document.getElementById('count').textContent =
      `${shown} lieu${shown !== 1 ? 'x' : ''} affiché${shown !== 1 ? 's' : ''} / ${geojson.features.length} géocodés`;
  }

  /* --- Event: Dept filter --- */
  document.querySelectorAll('#dept-filters button').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#dept-filters button').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentDept = btn.dataset.dept;
      render();
    });
  });

  /* --- Event: Cat filter (delegated, buttons added dynamically) --- */
  document.getElementById('cat-filters').addEventListener('click', e => {
    if (e.target.tagName !== 'BUTTON') return;
    document.querySelectorAll('#cat-filters button').forEach(b => b.classList.remove('active'));
    e.target.classList.add('active');
    currentCat = e.target.dataset.cat;
    render();
  });

  /* --- Event: Price sliders --- */
  const priceMinEl = document.getElementById('price-min');
  const priceMaxEl = document.getElementById('price-max');
  const priceLabel = document.getElementById('price-label');

  function updatePrice() {
    priceMin = parseInt(priceMinEl.value);
    priceMax = parseInt(priceMaxEl.value);
    if (priceMin > priceMax) { [priceMin, priceMax] = [priceMax, priceMin]; }
    priceLabel.textContent = `prix ${priceMin}–${priceMax}`;
    render();
  }

  priceMinEl.addEventListener('input', updatePrice);
  priceMaxEl.addEventListener('input', updatePrice);

  /* --- Event: Capacity sliders --- */
  const capMinEl = document.getElementById('cap-min');
  const capMaxEl = document.getElementById('cap-max');
  const capLabel = document.getElementById('cap-label');

  function updateCap() {
    capMin = parseInt(capMinEl.value);
    capMax = parseInt(capMaxEl.value);
    if (capMin > capMax) { [capMin, capMax] = [capMax, capMin]; }
    capLabel.textContent = `${capMin}–${capMax} pers`;
    render();
  }

  capMinEl.addEventListener('input', updateCap);
  capMaxEl.addEventListener('input', updateCap);

  /* --- Load GeoJSON data --- */
  fetch('salles_small_idf.geojson')
    .then(r => r.json())
    .then(data => {
      geojson = data;
      buildCatFilters(data.features);
      render();

      // Fit map bounds to data
      if (data.features.length) {
        const bounds = L.geoJSON(data).getBounds().pad(0.1);
        map.fitBounds(bounds);
      }
    })
    .catch(err => {
      document.getElementById('count').textContent = 'Erreur de chargement des données';
      console.error('GeoJSON load error:', err);
    });
})();