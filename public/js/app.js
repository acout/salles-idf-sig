// Prospection salles IDF — map + lightweight CRM in localStorage
const map = L.map('map').setView([48.86, 2.35], 10);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution:'© OpenStreetMap contributors', maxZoom:19 }).addTo(map);

const STORAGE_KEY = 'salles-idf-crm-v1';
const STATUS = {
  new:'À qualifier', shortlist:'Shortlist', contacted:'Contactée', applied:'Candidature envoyée',
  accepted:'OK / utilisable', rejected:'Refus / pas adaptée', used:'Déjà utilisée'
};
const STATUS_ORDER = Object.keys(STATUS);
const IDF_BBOX = { minLat:48.1, maxLat:49.1, minLon:1.4, maxLon:3.6 };
const state = { data:null, filtered:[], selectedId:null, markers:L.layerGroup().addTo(map), view:'map', filters:{ q:'', dept:'all', status:'all', capMax:20, sort:'fit' }, crm:{} };

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const insideIdf = (lat,lon) => lat>=IDF_BBOX.minLat && lat<=IDF_BBOX.maxLat && lon>=IDF_BBOX.minLon && lon<=IDF_BBOX.maxLon;
const today = () => new Date().toISOString().slice(0,10);

function loadCrm(){ try { state.crm = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}'); } catch { state.crm = {}; } }
function saveCrm(){ localStorage.setItem(STORAGE_KEY, JSON.stringify(state.crm)); }
function crmFor(id){ if(!state.crm[id]) state.crm[id] = { status:'new', notes:[], nextAction:'', nextActionDate:'', events:[], favorite:false, updatedAt:null }; return state.crm[id]; }
function touch(id){ crmFor(id).updatedAt = new Date().toISOString(); saveCrm(); }
function toast(msg){ const el=document.createElement('div'); el.className='toast'; el.textContent=msg; document.body.appendChild(el); setTimeout(()=>el.remove(),2200); }

function fitColor(s){ s=+s||0; if(s>=85)return'#0a7'; if(s>=70)return'#8bc34a'; if(s>=55)return'#ffc107'; return'#ff7043'; }
function statusPill(status){ return `<span class="pill status-${status||'new'}">${esc(STATUS[status]||STATUS.new)}</span>`; }
function venueId(p){ return p.id || p.name; }
function capacity(p){ return +(p.capacity_max_detected||0) || 999; }
function coordsOf(f){ const c=f.geometry?.coordinates; if(!c||c.length<2)return null; const [lon,lat]=c.map(Number); return Number.isFinite(lat)&&Number.isFinite(lon)&&insideIdf(lat,lon) ? [lat,lon] : null; }
function searchableText(f){ const p=f.properties, c=crmFor(venueId(p)); return [p.name,p.city,p.department,p.category,p.address,p.contact,p.price_text,p.pros,p.cons,c.status,c.nextAction,...(c.notes||[]).map(n=>n.text),...(c.events||[]).map(e=>`${e.date} ${e.label}`)].join(' ').toLowerCase(); }

function applyFilters(){
  const q = state.filters.q.trim().toLowerCase();
  state.filtered = state.data.features.filter(f => {
    const p=f.properties, id=venueId(p), c=crmFor(id), ll=coordsOf(f);
    if(!ll) return false;
    if(state.filters.dept!=='all' && p.department!==state.filters.dept) return false;
    if(state.filters.status!=='all' && c.status!==state.filters.status) return false;
    if(capacity(p) > +state.filters.capMax) return false;
    if(q && !searchableText(f).includes(q)) return false;
    return true;
  });
  sortFiltered();
}
function sortFiltered(){
  const sort=state.filters.sort;
  state.filtered.sort((a,b)=>{
    const pa=a.properties,pb=b.properties, ca=crmFor(venueId(pa)), cb=crmFor(venueId(pb));
    if(sort==='city') return String(pa.city||'').localeCompare(String(pb.city||''),'fr');
    if(sort==='capacity') return capacity(pa)-capacity(pb);
    if(sort==='status') return STATUS_ORDER.indexOf(ca.status||'new')-STATUS_ORDER.indexOf(cb.status||'new');
    if(sort==='nextAction') return String(ca.nextActionDate||'9999-99-99').localeCompare(String(cb.nextActionDate||'9999-99-99'));
    return (+pb.fit_score||0)-(+pa.fit_score||0);
  });
}

function jitter(lat,lon,i,total){ if(total<=1)return[lat,lon]; const angle=(i*137.508)*Math.PI/180; const ring=Math.floor(i/12)+1; const radius=0.00008*ring; return [lat+Math.sin(angle)*radius, lon+Math.cos(angle)*radius/Math.cos(lat*Math.PI/180)]; }
function popupHTML(f){
  const p=f.properties, id=venueId(p), c=crmFor(id);
  return `<div class="popup"><h3>${esc(p.name)}</h3>${statusPill(c.status||'new')} <span class="pill fit">fit ${esc(p.fit_score)}</span>
  <div class="info-row"><b>Ville</b> ${esc(p.city||'—')} · ${esc(p.department||'')}</div>
  <div class="info-row"><b>Capacité</b> ${esc(p.capacity_text||'—')}</div>
  <div class="info-row"><b>Prix</b> ${esc(p.price_text||'à confirmer')}</div>
  ${c.nextAction?`<div class="info-row"><b>Next</b> ${esc(c.nextAction)} ${c.nextActionDate?`(${esc(c.nextActionDate)})`:''}</div>`:''}
  <div class="detail-actions"><button class="primary-btn" onclick="openDetailById('${esc(id)}')">Ouvrir la fiche</button>${p.website?`<a class="secondary-btn" href="${esc(p.website)}" target="_blank">Site</a>`:''}</div></div>`;
}
function renderMap(){
  state.markers.clearLayers(); const buckets=new Map();
  state.filtered.forEach(f=>{ const [lat,lon]=coordsOf(f); const key=`${lat.toFixed(6)},${lon.toFixed(6)}`; if(!buckets.has(key))buckets.set(key,[]); buckets.get(key).push(f); });
  for(const bucket of buckets.values()) bucket.forEach((f,i)=>{ const p=f.properties,[lat,lon]=coordsOf(f),[jLat,jLon]=jitter(lat,lon,i,bucket.length); const marker=L.circleMarker([jLat,jLon],{radius:crmFor(venueId(p)).favorite?9:7,color:'#111',weight:crmFor(venueId(p)).favorite?2:1,fillColor:fitColor(+p.fit_score),fillOpacity:.85}).addTo(state.markers).bindPopup(popupHTML(f)+(bucket.length>1?`<div class="overlap-note">Point décalé : ${bucket.length} salles à la même coordonnée.</div>`:'')); marker.on('click',()=>selectVenue(venueId(p),false)); });
}

function cardHTML(f, compact=false){
  const p=f.properties, id=venueId(p), c=crmFor(id), note=c.notes?.[0]?.text;
  return `<article class="venue-card ${state.selectedId===id?'active':''}" data-id="${esc(id)}">
    <div class="venue-title">${c.favorite?'⭐ ':''}${esc(p.name)}</div>
    <div class="venue-meta">${statusPill(c.status||'new')}<span class="pill">${esc(p.department)}</span><span class="pill">${esc(p.city||'—')}</span><span class="pill fit">fit ${esc(p.fit_score)}</span></div>
    <div class="venue-small">${esc(p.category||'')} · cap. ${esc(p.capacity_text||'—')} · ${esc(p.price_text||'prix à confirmer')}</div>
    ${c.nextAction?`<div class="venue-note-preview">⏭️ ${esc(c.nextAction)} ${c.nextActionDate?`· ${esc(c.nextActionDate)}`:''}</div>`:''}
    ${note && !compact?`<div class="venue-note-preview">📝 ${esc(note).slice(0,130)}</div>`:''}
  </article>`;
}
function renderSidebarList(){ $('list-panel').innerHTML = state.filtered.slice(0,80).map(f=>cardHTML(f,true)).join('') || '<div class="empty">Aucune salle avec ces filtres.</div>'; document.querySelectorAll('.venue-card').forEach(el=>el.onclick=()=>selectVenue(el.dataset.id,true)); }
function renderTable(){
  const rows = state.filtered.map(f=>{ const p=f.properties,id=venueId(p),c=crmFor(id); const overdue=c.nextActionDate && c.nextActionDate<today(); return `<div class="table-row" data-id="${esc(id)}"><div><div class="table-name">${c.favorite?'⭐ ':''}${esc(p.name)}</div><div class="table-sub">${esc(p.city||'—')} · ${esc(p.category||'')}</div></div><div>${statusPill(c.status||'new')}</div><div>${esc(p.capacity_text||'—')}</div><div class="next-action-badge ${overdue?'overdue':''}">${esc(c.nextAction||'—')} ${c.nextActionDate?`<br>${esc(c.nextActionDate)}`:''}</div><div class="table-sub">fit ${esc(p.fit_score)} · prix ${esc(p.price_score)}</div></div>`; }).join('');
  $('venue-table').innerHTML = `<div class="table-row table-head"><div>Salle</div><div>Statut</div><div>Capacité</div><div>Prochaine action</div><div>Scores</div></div>${rows || '<div class="empty">Aucune salle.</div>'}`;
  document.querySelectorAll('#venue-table .table-row[data-id]').forEach(el=>el.onclick=()=>selectVenue(el.dataset.id,true));
}
function updateMetrics(){ const tracked=Object.values(state.crm).filter(v=>v.status&&v.status!=='new').length; const overdue=Object.values(state.crm).filter(v=>v.nextActionDate && v.nextActionDate<today()).length; $('metrics').textContent=`${state.filtered.length} affichées · ${tracked} suivies · ${overdue} relances en retard`; }
function renderAll(){ applyFilters(); renderMap(); renderSidebarList(); renderTable(); updateMetrics(); if(state.selectedId) renderDetail(state.selectedId); }

function findFeature(id){ return state.data.features.find(f=>venueId(f.properties)===id); }
function selectVenue(id, open=true){ state.selectedId=id; renderSidebarList(); if(open) openDetailById(id); }
window.openDetailById = function(id){ state.selectedId=id; renderDetail(id); $('detail-panel').classList.remove('hidden'); renderSidebarList(); };
function renderDetail(id){
  const f=findFeature(id); if(!f) return; const p=f.properties,c=crmFor(id); const notes=(c.notes||[]).map((n,i)=>`<div class="note-item"><div class="note-date">${esc(n.date)}</div><div>${esc(n.text)}</div><button class="danger-btn" data-del-note="${i}">Supprimer</button></div>`).join('') || '<p class="muted">Pas encore de note.</p>';
  const events=(c.events||[]).map((e,i)=>`<div class="event-row"><div><b>${esc(e.date||'date ?')}</b><br>${esc(e.label||'event')}</div><button class="danger-btn" data-del-event="${i}">×</button></div>`).join('') || '<p class="muted">Aucun event lié.</p>';
  $('detail-content').innerHTML = `<div class="detail-inner"><h2>${esc(p.name)}</h2><div class="venue-meta">${statusPill(c.status||'new')}<span class="pill">${esc(p.department)}</span><span class="pill">${esc(p.city||'—')}</span><span class="pill fit">fit ${esc(p.fit_score)}</span></div><p class="muted">${esc(p.address||'adresse à vérifier')}</p>
    <div class="detail-actions">${p.website?`<a class="primary-btn" href="${esc(p.website)}" target="_blank">Ouvrir site</a>`:''}${p.source_url?`<a class="secondary-btn" href="${esc(p.source_url)}" target="_blank">Source</a>`:''}<button class="secondary-btn" id="copy-contact">Copier contact</button><button class="secondary-btn" id="toggle-fav">${c.favorite?'Retirer ⭐':'Ajouter ⭐'}</button></div>
    <div class="section"><h3>Infos salle</h3><div class="detail-grid"><div><b>Capacité</b><br>${esc(p.capacity_text||'—')}</div><div><b>Prix</b><br>${esc(p.price_text||'à confirmer')}</div><div><b>Contact</b><br>${esc(p.contact||'—')}</div><div><b>Catégorie</b><br>${esc(p.category||'—')}</div></div>${p.pros?`<p><b>Pros</b> ${esc(p.pros)}</p>`:''}${p.cons?`<p><b>Cons</b> ${esc(p.cons)}</p>`:''}</div>
    <div class="section"><h3>Suivi prospection</h3><label class="field-label">Statut</label><select id="detail-status" class="input">${Object.entries(STATUS).map(([k,v])=>`<option value="${k}" ${c.status===k?'selected':''}>${v}</option>`).join('')}</select><div class="detail-grid"><div><label class="field-label">Prochaine action</label><input id="next-action" class="input" value="${esc(c.nextAction||'')}" placeholder="Appeler, relancer, envoyer dossier…"></div><div><label class="field-label">Date</label><input id="next-action-date" type="date" class="input" value="${esc(c.nextActionDate||'')}"></div></div><p class="help">Astuce : filtre ensuite par statut ou tri “prochaine action”.</p></div>
    <div class="section"><h3>Ajouter une note / appel</h3><textarea id="new-note" rows="4" placeholder="Ex: appelé le standard, salle dispo mercredi soir, demander attestation RC…"></textarea><div class="detail-actions"><button class="primary-btn" id="add-note">Ajouter note</button></div><div class="note-list">${notes}</div></div>
    <div class="section"><h3>Events réalisés ici</h3><div class="detail-grid"><input id="event-date" type="date" class="input"><input id="event-label" class="input" placeholder="Nom / type d’event"></div><div class="detail-actions"><button class="primary-btn" id="add-event">Ajouter event</button></div>${events}</div></div>`;
  bindDetailEvents(id);
}
function bindDetailEvents(id){ const c=crmFor(id); $('detail-status').onchange=e=>{c.status=e.target.value;touch(id);renderAll();}; $('next-action').onchange=e=>{c.nextAction=e.target.value;touch(id);renderAll();}; $('next-action-date').onchange=e=>{c.nextActionDate=e.target.value;touch(id);renderAll();}; $('add-note').onclick=()=>{const t=$('new-note').value.trim(); if(!t)return; c.notes.unshift({date:new Date().toLocaleString('fr-FR'),text:t}); touch(id); renderAll();}; $('add-event').onclick=()=>{const label=$('event-label').value.trim(); if(!label)return; c.events.unshift({date:$('event-date').value||today(),label}); c.status='used'; touch(id); renderAll();}; $('toggle-fav').onclick=()=>{c.favorite=!c.favorite;touch(id);renderAll();}; $('copy-contact').onclick=async()=>{const p=findFeature(id).properties; await navigator.clipboard?.writeText([p.name,p.contact,p.website].filter(Boolean).join('\n')); toast('Contact copié');}; document.querySelectorAll('[data-del-note]').forEach(b=>b.onclick=()=>{c.notes.splice(+b.dataset.delNote,1);touch(id);renderAll();}); document.querySelectorAll('[data-del-event]').forEach(b=>b.onclick=()=>{c.events.splice(+b.dataset.delEvent,1);touch(id);renderAll();}); }

function bindControls(){
  $('search').oninput=e=>{state.filters.q=e.target.value;renderAll();}; $('dept-filter').onchange=e=>{state.filters.dept=e.target.value;renderAll();}; $('status-filter').onchange=e=>{state.filters.status=e.target.value;renderAll();}; $('cap-max').oninput=e=>{state.filters.capMax=e.target.value;$('cap-val').textContent=`≤${e.target.value}`;renderAll();}; $('sort-by').onchange=e=>{state.filters.sort=e.target.value;renderAll();};
  document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>{state.view=b.dataset.view;document.querySelectorAll('[data-view]').forEach(x=>x.classList.toggle('active',x===b));$('map').classList.toggle('hidden',state.view!=='map');$('table-view').classList.toggle('hidden',state.view!=='list');setTimeout(()=>map.invalidateSize(),80);});
  $('close-detail').onclick=()=>$('detail-panel').classList.add('hidden'); $('open-sidebar').onclick=()=>$('sidebar').classList.add('open'); $('toggle-sidebar').onclick=()=>$('sidebar').classList.remove('open');
  $('export-json').onclick=()=>{const blob=new Blob([JSON.stringify({exportedAt:new Date().toISOString(),crm:state.crm},null,2)],{type:'application/json'}); const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download=`salles-idf-suivi-${today()}.json`; a.click(); URL.revokeObjectURL(a.href);};
  $('import-json').onchange=e=>{const file=e.target.files[0]; if(!file)return; const r=new FileReader(); r.onload=()=>{try{const obj=JSON.parse(r.result); state.crm=obj.crm||obj; saveCrm(); toast('Suivi importé'); renderAll();}catch{toast('Import impossible');}}; r.readAsText(file);};
}

fetch('salles_all_idf.geojson').then(r=>r.json()).then(j=>{ state.data=j; loadCrm(); bindControls(); renderAll(); if(state.filtered.length){ const bounds=L.latLngBounds(state.filtered.map(coordsOf).filter(Boolean)); map.fitBounds(bounds.pad(.08)); } });