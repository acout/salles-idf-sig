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
const state = { data:null, venues:null, candidates:null, filtered:[], selectedId:null, markers:L.layerGroup().addTo(map), view:'map', filters:{ q:'', dataset:'all', dept:'all', status:'all', quality:'all', tagFilters:new Set(), capMax:100, sort:'fit' }, crm:{}, quality:{} };

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const insideIdf = (lat,lon) => lat>=IDF_BBOX.minLat && lat<=IDF_BBOX.maxLat && lon>=IDF_BBOX.minLon && lon<=IDF_BBOX.maxLon;
const today = () => new Date().toISOString().slice(0,10);

function loadCrm(){ try { state.crm = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}'); } catch { state.crm = {}; } }
function saveCrm(){ localStorage.setItem(STORAGE_KEY, JSON.stringify(state.crm)); }
function crmFor(id){ if(!state.crm[id]) state.crm[id] = { status:'new', notes:[], nextAction:'', nextActionDate:'', events:[], favorite:false, updatedAt:null, overrides:{} }; if(!state.crm[id].overrides) state.crm[id].overrides = {}; return state.crm[id]; }
function touch(id){ crmFor(id).updatedAt = new Date().toISOString(); saveCrm(); }
function toast(msg){ const el=document.createElement('div'); el.className='toast'; el.textContent=msg; document.body.appendChild(el); setTimeout(()=>el.remove(),2200); }

function fitColor(s){ s=+s||0; if(s>=85)return'#0a7'; if(s>=70)return'#8bc34a'; if(s>=55)return'#ffc107'; return'#ff7043'; }
function statusPill(status){ return `<span class="pill status-${status||'new'}">${esc(STATUS[status]||STATUS.new)}</span>`; }
function venueId(p){ return p.id || p.candidate_id || p.name; }
function isCandidate(p){ return p._dataset === 'candidate'; }
function isAggregator(p){ return String(p.is_aggregator||'').toLowerCase()==='yes'; }
function datasetLabel(p){ if(isAggregator(p)) return 'Agrégateur'; return isCandidate(p) ? 'Candidat Beyond' : 'Salle qualifiée'; }
function formalMissing(p){ return String(p.missing_formal_fields||'').trim(); }
function formalQuestions(p){ return String(p.email_questions||'').trim(); }
function rentalStatus(p){ return String(p.rental_possible_status||'unclear').trim() || 'unclear'; }
function rentalLabel(p){ const s=rentalStatus(p); return s==='possible'?'Location possible':s==='unlikely'?'Probablement non louable':'Location à vérifier'; }
function capacity(p){ return +(p.capacity_max_detected||p.capacity_max||0) || (isCandidate(p) ? 0 : 999); }
function displayProps(f){
  const raw=f.properties, c=crmFor(venueId(raw)), o=c.overrides||{};
  const dp={...raw};
  const ov={};
  if(!isBlank(o.contactOverride)){ dp.contact=o.contactOverride.trim(); ov.contact=true; }
  if(!isBlank(o.priceOverride)){ dp.price_text=o.priceOverride.trim(); ov.price=true; }
  if(!isBlank(o.capacityOverride)){ dp.capacity_text=o.capacityOverride.trim(); ov.capacity=true; }
  if(!isBlank(o.addressOverride)){ dp.address=o.addressOverride.trim(); ov.address=true; }
  dp._ov=ov; dp._hasOverride=Object.keys(ov).length>0; dp._sourceReliability=o.sourceReliability||''; dp._enrichmentNote=o.enrichmentNote||'';
  return dp;
}
function originalHint(raw,dp,key,label){ return dp._ov?.[key] ? `<div class="src-orig">Source ${label} : ${esc(raw[key==='price'?'price_text':key==='capacity'?'capacity_text':key]||'—')}</div>` : ''; }
function overrideBadgeHTML(dp){ const badges=[]; if(dp._hasOverride) badges.push('<span class="qbadge edited">corrigé local</span>'); if(dp._sourceReliability==='reliable') badges.push('<span class="qbadge ok">Source OK</span>'); if(dp._sourceReliability==='uncertain') badges.push('<span class="qbadge issue">Source ?</span>'); if(dp._sourceReliability==='bad') badges.push('<span class="qbadge bad">Source mauvaise</span>'); return badges.join(''); }
function coordsOf(f){ const c=f.geometry?.coordinates; if(!c||c.length<2||c[0]===null||c[1]===null)return null; const [lon,lat]=c.map(Number); return Number.isFinite(lat)&&Number.isFinite(lon)&&insideIdf(lat,lon) ? [lat,lon] : null; }
const QUALITY_LABELS = {
  contact_missing:'Contact ?', price_missing:'Prix ?', capacity_uncertain:'Capacité ?', duplicate_suspect:'Doublon ?', geocode_suspect:'Géocode ?', aggregator_listing:'Agrégateur', formal_missing:'À demander', scrape_failed:'Scrape KO', rental_possible:'Location OK', rental_unclear:'Loc ?', rental_unlikely:'Pas louable ?'
};
function isBlank(v){ const t=String(v??'').trim().toLowerCase(); return !t || ['—','-','n/a','na','non renseigné','non renseigne','à confirmer','a confirmer','inconnu','unknown'].includes(t) || t.includes('à confirmer') || t.includes('a confirmer'); }
function normText(v){ return String(v??'').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9]+/g,' ').trim(); }
function normName(p){ return normText(p.name).replace(/\b(maison|salle|espace|centre|municipal|municipale|association|associations|paris|idf)\b/g,'').replace(/\s+/g,' ').trim(); }
function normSite(v){ try{ const u=new URL(String(v||'')); return u.hostname.replace(/^www\./,'')+u.pathname.replace(/\/$/,''); }catch{return '';}}
function qualityFor(id){ return state.quality[id] || {issues:[], score:0}; }
function tagMatches(tag, f, p, id){
  const q=qualityFor(id), c=crmFor(id);
  if(tag==='candidate') return isCandidate(p);
  if(tag==='venue') return !isCandidate(p) && !isAggregator(p);
  if(tag==='favorite') return !!c.favorite;
  if(tag==='rental_possible') return rentalStatus(p)==='possible';
  if(tag==='rental_unclear') return rentalStatus(p)==='unclear';
  if(tag==='rental_unlikely') return rentalStatus(p)==='unlikely';
  return q.issues.includes(tag);
}
function activeTagLabels(){ return [...state.filters.tagFilters].map(t=>QUALITY_LABELS[t]||({candidate:'Candidat Beyond',venue:'Salle qualifiée',favorite:'⭐ Favori'}[t])||t); }
function qualityBadgesHTML(id){ const f=findFeature(id), dp=f?displayProps(f):null, extra=dp?overrideBadgeHTML(dp):''; const q=qualityFor(id); const base=!q.issues.length ? '<span class="qbadge ok">OK data</span>' : q.issues.map(k=>`<span class="qbadge issue">${esc(QUALITY_LABELS[k]||k)}</span>`).join(''); return base+extra; }
function buildQuality(){
  state.quality = {};
  const nameMap=new Map(), siteMap=new Map(), coordMap=new Map();
  state.data.features.forEach(f=>{ const p=f.properties,id=venueId(p), c=f.geometry?.coordinates||[]; const n=normName(p), site=normSite(p.website||p.source_url), hasCoord=c.length>=2 && c[0]!==null && c[1]!==null && Number.isFinite(+c[0]) && Number.isFinite(+c[1]), coord=hasCoord?`${(+c[1]).toFixed(5)},${(+c[0]).toFixed(5)}`:''; if(n){ if(!nameMap.has(n))nameMap.set(n,[]); nameMap.get(n).push(id);} if(site){ if(!siteMap.has(site))siteMap.set(site,[]); siteMap.get(site).push(id);} if(coord){ if(!coordMap.has(coord))coordMap.set(coord,[]); coordMap.get(coord).push({id,n}); } });
  state.data.features.forEach(f=>{ const raw=f.properties,id=venueId(raw),p=displayProps(f), issues=[]; const c=f.geometry?.coordinates||[]; const lat=+c[1], lon=+c[0];
    if(isAggregator(p)) issues.push('aggregator_listing');
    if(formalMissing(p)) issues.push('formal_missing');
    if(String(p.formal_extraction_status||'').includes('failed')) issues.push('scrape_failed');
    if(rentalStatus(p)==='unclear') issues.push('rental_unclear');
    if(rentalStatus(p)==='unlikely') issues.push('rental_unlikely');
    if(isBlank(p.contact)) issues.push('contact_missing');
    if(isBlank(p.price_text)) issues.push('price_missing');
    if(!p._ov.capacity && (isBlank(p.capacity_text) || capacity(p)>=999)) issues.push('capacity_uncertain');
    const n=normName(p), site=normSite(p.website||p.source_url), hasCoord=c.length>=2 && c[0]!==null && c[1]!==null && Number.isFinite(lat) && Number.isFinite(lon), coord=hasCoord?`${lat.toFixed(5)},${lon.toFixed(5)}`:'';
    const sameName=n && (nameMap.get(n)||[]).length>1, sameSite=site && (siteMap.get(site)||[]).length>1;
    const sameCoordClose=coord && (coordMap.get(coord)||[]).some(o=>o.id!==id && (o.n===n || o.n.includes(n) || n.includes(o.n)));
    if(sameName || sameSite || sameCoordClose) issues.push('duplicate_suspect');
    const gs=Number(p.geocode_score); if(isBlank(p.address) || (Number.isFinite(gs) && gs<0.55) || !hasCoord || !insideIdf(lat,lon)) issues.push('geocode_suspect');
    state.quality[id] = { issues:[...new Set(issues)], score:issues.length };
  });
}
function searchableText(f){ const raw=f.properties, p=displayProps(f), c=crmFor(venueId(raw)); return [p.name,p.city,p.department,p.category,p.address,p.contact,p.price_text,p.capacity_text,p.evidence_text,p.formal_evidence_text,p.missing_formal_fields,p.email_questions,p.rental_possible_status,p.rental_positive_signals,p.rental_negative_signals,p.aggregator_domain,p.score_reasons,p._enrichmentNote,p.pros,p.cons,c.status,c.nextAction,...(c.notes||[]).map(n=>n.text),...(c.events||[]).map(e=>`${e.date} ${e.label}`)].join(' ').toLowerCase(); }

function nextStatus(status){ const i=STATUS_ORDER.indexOf(status||'new'); return STATUS_ORDER[Math.min(i+1, STATUS_ORDER.length-1)]; }
function previousStatus(status){ const i=STATUS_ORDER.indexOf(status||'new'); return STATUS_ORDER[Math.max(i-1, 0)]; }
function setVenueStatus(id,status){ const c=crmFor(id); c.status=status; touch(id); renderAll(); toast(`Statut : ${STATUS[status]}`); }
function venueKind(p){ const txt=[p.category,p.name,p.source_url,p.website].join(' ').toLowerCase(); if(txt.includes('mairie')||txt.includes('municip')||txt.includes('mvac')||txt.includes('association')||txt.includes('anim')) return 'public'; if(txt.includes('cowork')) return 'cowork'; return 'generic'; }
function callScriptFor(f){ const p=displayProps(f); const kind=venueKind(p); const intro = kind==='public' ? 'Bonjour, je vous appelle pour une demande de mise à disposition / location d’une petite salle.' : 'Bonjour, je cherche une petite salle de réunion à louer pour un atelier.'; return `${intro}\n\nJe cherche une salle pour environ 10 à 20 personnes en Île-de-France.\nSalle repérée : ${p.name}\nAdresse : ${p.address || p.city || ''}\n\nQuestions rapides :\n1. Est-ce que vous accueillez ce type de réunion / atelier ?\n2. Quelle est la capacité exacte et la disposition possible ?\n3. Quels sont les tarifs (heure / demi-journée / journée) ?\n4. Quelles disponibilités en soirée ou week-end ?\n5. Quels documents faut-il fournir (association, assurance RC, descriptif) ?\n6. À quelle adresse mail envoyer une demande formelle ?\n\nMerci beaucoup.`; }
function emailFor(f){ const p=displayProps(f); const qs=formalQuestions(p); return `Bonjour,\n\nJe vous contacte au sujet de la salle ${p.name}.\n\nJe cherche une petite salle pour organiser un atelier / temps collectif d’environ 10 à 20 personnes.\n\nPouvez-vous me confirmer :\n- la capacité exacte de la salle ;\n- les tarifs heure / demi-journée / journée ;\n- les disponibilités possibles en soirée ou week-end ;\n- les conditions de réservation et documents nécessaires ;\n- la personne à contacter pour déposer une demande.${qs?`\n\nPoints restant à confirmer d’après le scraping : ${qs}`:''}\n\nLieu repéré : ${p.address || p.city || ''}\n${p.website ? `Site : ${p.website}\n` : ''}\nMerci beaucoup,\nAnthony`; }
function extractEmail(p){ const txt=[p.contact,p.email,p.source_url,p.website].filter(Boolean).join(' '); const m=txt.match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i); return m?m[0]:''; }
function emailSubjectFor(f){ const p=displayProps(f); return `Demande de location / mise à disposition — ${p.name}`; }
function gmailComposeUrl(f){ const p=displayProps(f), to=extractEmail(p), su=emailSubjectFor(f), body=emailFor(f); return `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(to)}&su=${encodeURIComponent(su)}&body=${encodeURIComponent(body)}`; }
function directionsUrl(f){ const p=displayProps(f), c=coordsOf(f); const dest=c?`${c[0]},${c[1]}`:(p.address||p.city||p.name||''); return `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(dest)}`; }
function openGmailFor(f){ window.open(gmailComposeUrl(f),'_blank','noopener'); }
async function copyText(text,label='Copié'){ try{ await navigator.clipboard.writeText(text); toast(label); } catch { const ta=document.createElement('textarea'); ta.value=text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove(); toast(label); } }

function applyFilters(){
  const q = state.filters.q.trim().toLowerCase();
  state.filtered = state.data.features.filter(f => {
    const p=f.properties, id=venueId(p), c=crmFor(id);
    if(state.filters.dataset==='venues' && isCandidate(p)) return false;
    if(state.filters.dataset==='candidates' && !isCandidate(p)) return false;
    if(state.filters.dept!=='all' && p.department!==state.filters.dept) return false;
    if(state.filters.status!=='all' && c.status!==state.filters.status) return false;
    if(state.filters.quality==='favorites' && !c.favorite) return false;
    if(['rental_possible','rental_unclear','rental_unlikely'].includes(state.filters.quality)){
      const want=state.filters.quality.replace('rental_','');
      if(rentalStatus(p)!==want) return false;
    } else if(state.filters.quality!=='all'){ const q=qualityFor(id); if(state.filters.quality==='any' ? q.score===0 : !q.issues.includes(state.filters.quality)) return false; }
    if(state.filters.tagFilters.size && ![...state.filters.tagFilters].every(tag=>tagMatches(tag, f, p, id))) return false;
    if(capacity(p) && capacity(p) > +state.filters.capMax) return false;
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
    if(sort==='quality') return qualityFor(venueId(pb)).score-qualityFor(venueId(pa)).score || (+pb.fit_score||0)-(+pa.fit_score||0);
    return (+pb.fit_score||0)-(+pa.fit_score||0);
  });
}

function jitter(lat,lon,i,total){ if(total<=1)return[lat,lon]; const angle=(i*137.508)*Math.PI/180; const ring=Math.floor(i/12)+1; const radius=0.00008*ring; return [lat+Math.sin(angle)*radius, lon+Math.cos(angle)*radius/Math.cos(lat*Math.PI/180)]; }
function popupHTML(f){
  const raw=f.properties, p=displayProps(f), id=venueId(raw), c=crmFor(id);
  return `<div class="popup"><h3>${esc(p.name)}</h3><span class="pill dataset-${isAggregator(p)?'aggregator':esc(p._dataset||'venue')}">${datasetLabel(p)}</span> <span class="pill rental-${esc(rentalStatus(p))}">${rentalLabel(p)}</span> ${statusPill(c.status||'new')} <span class="pill fit">fit ${esc(p.fit_score||p.fit_beyond_score)}</span>
  <div class="info-row"><b>Ville</b> ${esc(p.city||'—')} · ${esc(p.department||'')}</div>
  <div class="info-row"><b>Capacité</b> ${esc(p.capacity_text||'—')}</div>
  <div class="info-row"><b>Prix</b> ${esc(p.price_text||'à confirmer')}</div>
  ${c.nextAction?`<div class="info-row"><b>Next</b> ${esc(c.nextAction)} ${c.nextActionDate?`(${esc(c.nextActionDate)})`:''}</div>`:''}
  <div class="detail-actions"><button class="primary-btn" onclick="openDetailById('${esc(id)}')">Ouvrir la fiche</button>${p.website?`<a class="secondary-btn" href="${esc(p.website)}" target="_blank">Site</a>`:''}<a class="secondary-btn" href="${esc(directionsUrl(f))}" target="_blank">Itinéraire</a></div></div>`;
}
function renderMap(){
  state.markers.clearLayers(); const buckets=new Map();
  state.filtered.filter(coordsOf).forEach(f=>{ const [lat,lon]=coordsOf(f); const key=`${lat.toFixed(6)},${lon.toFixed(6)}`; if(!buckets.has(key))buckets.set(key,[]); buckets.get(key).push(f); });
  for(const bucket of buckets.values()) bucket.forEach((f,i)=>{ const p=f.properties,[lat,lon]=coordsOf(f),[jLat,jLon]=jitter(lat,lon,i,bucket.length); const marker=L.circleMarker([jLat,jLon],{radius:crmFor(venueId(p)).favorite?9:7,color:'#111',weight:crmFor(venueId(p)).favorite?2:1,fillColor:isAggregator(p)?'#f97316':(isCandidate(p)?'#7c3aed':fitColor(+p.fit_score)),fillOpacity:.85}).addTo(state.markers).bindPopup(popupHTML(f)+(bucket.length>1?`<div class="overlap-note">Point décalé : ${bucket.length} salles à la même coordonnée.</div>`:'')); marker.on('click',()=>selectVenue(venueId(p),false)); });
}

function cardHTML(f, compact=false){
  const raw=f.properties, p=displayProps(f), id=venueId(raw), c=crmFor(id), note=c.notes?.[0]?.text;
  return `<article class="venue-card ${state.selectedId===id?'active':''}" data-id="${esc(id)}">
    <div class="venue-title">${c.favorite?'⭐ ':''}${esc(p.name)}</div>
    <div class="venue-meta">${statusPill(c.status||'new')}<span class="pill dataset-${isAggregator(p)?'aggregator':esc(p._dataset||'venue')}">${datasetLabel(p)}</span><span class="pill rental-${esc(rentalStatus(p))}">${rentalLabel(p)}</span><span class="pill">${esc(p.department)}</span><span class="pill">${esc(p.city||'—')}</span><span class="pill fit">fit ${esc(p.fit_score)}</span></div>
    <div class="quality-badges">${qualityBadgesHTML(id)}</div>
    <div class="venue-small">${esc(p.category||'')} · cap. ${esc(p.capacity_text||'—')} · ${esc(p.price_text||'prix à confirmer')}${formalMissing(p)?` · à demander: ${esc(formalMissing(p))}`:''}</div>
    ${c.nextAction?`<div class="venue-note-preview">⏭️ ${esc(c.nextAction)} ${c.nextActionDate?`· ${esc(c.nextActionDate)}`:''}</div>`:''}
    ${note && !compact?`<div class="venue-note-preview">📝 ${esc(note).slice(0,130)}</div>`:''}
  </article>`;
}
function renderSidebarList(){ $('list-panel').innerHTML = state.filtered.slice(0,80).map(f=>cardHTML(f,true)).join('') || '<div class="empty">Aucune salle avec ces filtres.</div>'; document.querySelectorAll('.venue-card').forEach(el=>el.onclick=()=>selectVenue(el.dataset.id,true)); }
function renderTable(){
  const rows = state.filtered.map(f=>{ const raw=f.properties,p=displayProps(f),id=venueId(raw),c=crmFor(id); const overdue=c.nextActionDate && c.nextActionDate<today(); return `<div class="table-row" data-id="${esc(id)}"><div><div class="table-name">${c.favorite?'⭐ ':''}${esc(p.name)}</div><div class="table-sub">${esc(p.city||'—')} · ${esc(p.category||'')} · ${datasetLabel(p)}</div></div><div>${statusPill(c.status||'new')}<div class="quality-badges">${qualityBadgesHTML(id)}</div></div><div>${esc(p.capacity_text||'—')}</div><div class="next-action-badge ${overdue?'overdue':''}">${esc(c.nextAction||'—')} ${c.nextActionDate?`<br>${esc(c.nextActionDate)}`:''}</div><div class="table-sub">fit ${esc(p.fit_score||p.fit_beyond_score||'—')} · act. ${esc(p.actionability_score||p.price_score||'—')}</div></div>`; }).join('');
  $('venue-table').innerHTML = `<div class="table-row table-head"><div>Salle</div><div>Statut</div><div>Capacité</div><div>Prochaine action</div><div>Scores</div></div>${rows || '<div class="empty">Aucune salle.</div>'}`;
  document.querySelectorAll('#venue-table .table-row[data-id]').forEach(el=>el.onclick=()=>selectVenue(el.dataset.id,true));
}
function pipelineCard(f){
  const raw=f.properties, p=displayProps(f), id=venueId(raw), c=crmFor(id), overdue=c.nextActionDate && c.nextActionDate<today();
  const next=nextStatus(c.status||'new'), prev=previousStatus(c.status||'new');
  return `<div class="pipeline-card" data-id="${esc(id)}">
    <div class="pipeline-card-title" data-open="${esc(id)}">${c.favorite?'⭐ ':''}${esc(p.name)}</div>
    <div class="pipeline-card-meta">${esc(p.city||'—')} · ${esc(p.department)} · ${datasetLabel(p)} · ${rentalLabel(p)} · fit ${esc(p.fit_score||p.fit_beyond_score||'—')}</div>
    <div class="quality-badges">${qualityBadgesHTML(id)}</div>
    ${c.nextAction?`<div class="venue-note-preview ${overdue?'overdue':''}">⏭️ ${esc(c.nextAction)} ${c.nextActionDate?`· ${esc(c.nextActionDate)}`:''}</div>`:''}
    <div class="pipeline-card-actions">
      <button class="mini-btn" data-status="${esc(prev)}" data-id="${esc(id)}">← ${esc(STATUS[prev])}</button>
      <button class="mini-btn primary" data-status="${esc(next)}" data-id="${esc(id)}">${esc(STATUS[next])} →</button>
      <button class="mini-btn" data-copy-call="${esc(id)}">Script appel</button>
      <button class="mini-btn" data-copy-email="${esc(id)}">Copier email</button>
      <button class="mini-btn" data-open-gmail="${esc(id)}">Gmail</button>
      <a class="mini-btn" href="${esc(directionsUrl(f))}" target="_blank" onclick="event.stopPropagation()">Itinéraire</a>
    </div>
  </div>`;
}
function renderPipeline(){
  const grouped = Object.fromEntries(STATUS_ORDER.map(k=>[k, []]));
  state.filtered.forEach(f=>{ const c=crmFor(venueId(f.properties)); grouped[c.status||'new'].push(f); });
  $('pipeline-board').innerHTML = STATUS_ORDER.map(status => `<section class="pipeline-column"><div class="pipeline-head"><h3>${esc(STATUS[status])}</h3><span class="pipeline-count">${grouped[status].length}</span></div>${grouped[status].slice(0,60).map(pipelineCard).join('') || '<div class="empty">—</div>'}</section>`).join('');
  document.querySelectorAll('[data-open]').forEach(el=>el.onclick=()=>openDetailById(el.dataset.open));
  document.querySelectorAll('[data-status]').forEach(btn=>btn.onclick=e=>{ e.stopPropagation(); setVenueStatus(btn.dataset.id, btn.dataset.status); });
  document.querySelectorAll('[data-copy-call]').forEach(btn=>btn.onclick=e=>{ e.stopPropagation(); copyText(callScriptFor(findFeature(btn.dataset.copyCall)), 'Script d’appel copié'); });
  document.querySelectorAll('[data-copy-email]').forEach(btn=>btn.onclick=e=>{ e.stopPropagation(); copyText(emailFor(findFeature(btn.dataset.copyEmail)), 'Email copié'); });
  document.querySelectorAll('[data-open-gmail]').forEach(btn=>btn.onclick=e=>{ e.stopPropagation(); openGmailFor(findFeature(btn.dataset.openGmail)); });
}
function updateMetrics(){ const tracked=Object.values(state.crm).filter(v=>v.status&&v.status!=='new').length; const quality=state.filtered.filter(f=>qualityFor(venueId(f.properties)).score>0).length; const cand=state.filtered.filter(f=>isCandidate(f.properties)).length; const aggs=state.filtered.filter(f=>isAggregator(f.properties)).length; const rentOk=state.filtered.filter(f=>rentalStatus(f.properties)==='possible').length; const rentNo=state.filtered.filter(f=>rentalStatus(f.properties)==='unlikely').length; const mapped=state.filtered.filter(coordsOf).length; const tags=activeTagLabels(); $('metrics').textContent=`${state.filtered.length} affichées · ${cand} candidats · ${aggs} agrégateurs · ${rentOk} location OK · ${rentNo} non louables prob. · ${mapped} cartographiées · ${quality} à vérifier${tags.length?' · tags: '+tags.join(' + '):''}`; }

/* ── Vérif Import view ─────────────────────────── */
state.funnelItems=[];
const FUNNEL_STAGES=[
  {key:'L0_aggregator',label:'Agrégateur / annuaire',icon:'📥',color:'#fb923c'},
  {key:'L2_filtered_geo',label:'Filtré géo (hors IDF / homonyme)',icon:'🌍',color:'#f87171'},
  {key:'L2_filtered_reliability',label:'Filtré fiabilité (S1/S2/S0)',icon:'⚠️',color:'#fbbf24'},
  {key:'L3_not_venue',label:'Non-venue : PDF, listing, planning…',icon:'❌',color:'#ef4444'},
  {key:'L3_valid_but_missing',label:'Salle valide non importée',icon:'🔧',color:'#f59e0b'},
  {key:'L4_import_queue',label:'✅ Importé dans la carte',icon:'✅',color:'#22c55e'},
];
function renderFunnel(){
  if(!state.funnelItems.length){renderFunnelEmpty();return;}
  const sc=state.funnelStageCounts||{};
  const summaryHTML=FUNNEL_STAGES.map(s=>`<div class="funnel-row" style="border-left:4px solid ${s.color};padding:6px 12px;margin:6px 0;border-radius:8px;background:#fff;cursor:pointer" data-funnel-stage="${s.key}">
    <span style="font-weight:700">${s.icon} ${s.label}</span>
    <span style="float:right;font-weight:800;font-size:16px">${sc[s.key]||0}</span>
  </div>`).join('') + `<div class="funnel-row" style="border-left:4px solid #94a3b8;padding:6px 12px;margin:6px 0;border-radius:8px;background:#fff"><span style="font-weight:700">Total</span><span style="float:right;font-weight:800;font-size:16px">${state.funnelItems.length}</span></div>`;
  $('funnel-summary').innerHTML=summaryHTML;
  document.querySelectorAll('[data-funnel-stage]').forEach(el=>el.onclick=()=>{
    $('funnel-stage-filter').value=el.dataset.funnelStage==='L4_import_queue'?'L4_import_queue':el.dataset.funnelStage;
    renderFunnel();
  });

  const stageFilter=$('funnel-stage-filter')?.value||'all';
  const sourceFilter=$('funnel-source-filter')?.value||'all';
  const q=(state.filters.q||'').toLowerCase();
  let items=state.funnelItems;
  if(stageFilter!=='all') items=items.filter(i=>i.stage===stageFilter);
  if(sourceFilter!=='all') items=items.filter(i=>i.source_reliability===sourceFilter);
  if(q) items=items.filter(i=>(i.name+' '+i.city+' '+i.stop_reason).toLowerCase().includes(q));

  $('funnel-items').innerHTML=items.slice(0,150).map(i=>{
    const stage=FUNNEL_STAGES.find(s=>s.key===i.stage);
    const sc2=stage?stage.color:'#94a3b8';
    const sl=stage?stage.label:i.stage;
    const si=stage?stage.icon:'❓';
    return `<div class="funnel-item" style="border-left:4px solid ${sc2};padding:8px 12px;margin:4px 0;background:#fff;border-radius:10px">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:4px">
        <div style="font-weight:700;max-width:55%">${esc(i.name||'Sans nom')}</div>
        <div><span class="pill" style="font-size:10px;background:${sc2};color:#fff">${si} ${esc(sl)}</span> ${i.source_reliability?`<span class="pill rel-${esc(i.source_reliability)}" style="font-size:10px">${esc(i.source_reliability)}</span>`:''} ${i.rental_possible?`<span class="pill rental-${esc(i.rental_possible)}" style="font-size:10px">${esc(i.rental_possible)}</span>`:''}</div>
      </div>
      <div style="font-size:12px;color:#344054;margin-top:3px">${esc(i.stop_reason)}</div>
      <div style="font-size:11px;color:#667085;margin-top:2px">${esc(i.city||'')} ${i.page_type?`· <span class="pill" style="font-size:9px">${esc(i.page_type.replace(/_/g,' '))}</span>`:''} ${i.source_url?`· <a href="${esc(i.source_url)}" target="_blank" style="color:#0a7;font-size:11px">site</a>`:''}</div>
    </div>`;
  }).join('')||'<div class="empty">Aucun item avec ces filtres.</div>';
}
function renderFunnelEmpty(){
  $('funnel-summary').innerHTML='<div class="empty" style="padding:40px">Chargement des données de vérif…</div>';
  $('funnel-items').innerHTML='';
}
function renderAll(){ buildQuality(); applyFilters(); renderMap(); renderSidebarList(); renderTable(); renderPipeline(); renderFunnel(); updateMetrics(); if(state.selectedId) renderDetail(state.selectedId); }

function findFeature(id){ return state.data.features.find(f=>venueId(f.properties)===id); }
function selectVenue(id, open=true){ state.selectedId=id; renderSidebarList(); if(open) openDetailById(id); }
window.openDetailById = function(id){ state.selectedId=id; renderDetail(id); $('detail-panel').classList.remove('hidden'); renderSidebarList(); };
function renderDetail(id){
  const f=findFeature(id); if(!f) return; const raw=f.properties, p=displayProps(f), c=crmFor(id), o=c.overrides||{}; const notes=(c.notes||[]).map((n,i)=>`<div class="note-item"><div class="note-date">${esc(n.date)}</div><div>${esc(n.text)}</div><button class="danger-btn" data-del-note="${i}">Supprimer</button></div>`).join('') || '<p class="muted">Pas encore de note.</p>';
  const events=(c.events||[]).map((e,i)=>`<div class="event-row"><div><b>${esc(e.date||'date ?')}</b><br>${esc(e.label||'event')}</div><button class="danger-btn" data-del-event="${i}">×</button></div>`).join('') || '<p class="muted">Aucun event lié.</p>';
  $('detail-content').innerHTML = `<div class="detail-inner"><h2>${esc(p.name)}</h2><div class="venue-meta">${statusPill(c.status||'new')}<span class="pill">${esc(p.department)}</span><span class="pill">${esc(p.city||'—')}</span><span class="pill fit">fit ${esc(p.fit_score)}</span></div><div class="quality-badges detail-quality">${qualityBadgesHTML(id)}</div><p class="muted">${esc(p.address||'adresse à vérifier')}</p>
    <div class="detail-actions">${p.website?`<a class="primary-btn" href="${esc(p.website)}" target="_blank">Ouvrir site</a>`:''}${p.source_url?`<a class="secondary-btn" href="${esc(p.source_url)}" target="_blank">Source</a>`:''}<a class="secondary-btn" href="${esc(directionsUrl(f))}" target="_blank">Itinéraire</a><button class="secondary-btn" id="copy-contact">Copier contact</button><button class="secondary-btn" id="copy-call-script">Script appel</button><button class="secondary-btn" id="copy-email-template">Copier email</button><button class="secondary-btn" id="open-gmail-compose">Ouvrir Gmail</button><button class="secondary-btn" id="toggle-fav">${c.favorite?'Retirer ⭐':'Ajouter ⭐'}</button></div>
    <div class="section"><h3>Infos salle</h3><div class="detail-grid"><div><b>Capacité</b><br>${esc(p.capacity_text||'—')}${originalHint(raw,p,'capacity','capacité')}</div><div><b>Prix</b><br>${esc(p.price_text||'à confirmer')}${originalHint(raw,p,'price','prix')}</div><div><b>Contact</b><br>${esc(p.contact||'—')}${originalHint(raw,p,'contact','contact')}</div><div><b>Catégorie</b><br>${esc(p.category||'—')}</div></div>${p.pros?`<p><b>Pros</b> ${esc(p.pros)}</p>`:''}${p.cons?`<p><b>Cons</b> ${esc(p.cons)}</p>`:''}</div>
    <div class="section formal-section"><h3>Source &amp; lineage</h3><div class="detail-grid"><div><b>Type source</b><br>${p.page_type?`<span class="pill src-${esc(p.page_type)}">${esc(p.page_type.replace(/_/g,' '))}</span>`:datasetLabel(p)}${p.source_reliability?` <span class="pill rel-${esc(p.source_reliability)}">${esc(p.source_reliability)}</span>`:''} ${p.aggregator_domain?` · ${esc(p.aggregator_domain)}`:''}</div><div><b>Zone</b><br>${p.geo_status?`<span class="pill geo-${esc(p.geo_status)}">${esc(p.geo_status.replace(/_/g,' '))}</span>`:'—'}</div><div><b>Observations</b><br>${esc(p.observation_count||1)} source(s)</div><div><b>Extraction IA</b><br>${p.formal_extraction_status==='ai_extracted'?'<span class="qbadge ok">IA structurée</span>':esc(p.formal_extraction_status||'non testé')}</div></div>
        ${p.specific_rental_page_url?`<p class="help"><b>Page location :</b> <a href="${esc(p.specific_rental_page_url)}" target="_blank">${esc(p.specific_rental_page_url.length>70?p.specific_rental_page_url.slice(0,67)+'...':p.specific_rental_page_url)}</a></p>`:''} 
        <div class="detail-grid"><div><b>Location</b><br><span class="pill rental-${esc(rentalStatus(p))}">${rentalLabel(p)}</span>${p.rental_possible_confidence?` <small>conf. ${esc(p.rental_possible_confidence)}</small>`:''}</div><div><b>Complétude</b><br>${esc(p.formal_completeness_score||'—')}</div><div><b>Liens extraits</b><br>${esc(p.aggregator_child_links_count||'0')}</div></div>${formalMissing(p)?`<p class="missing-box"><b>À demander par email :</b> ${esc(formalMissing(p))}<br><span>${esc(formalQuestions(p))}</span></p>`:'<p class="qbadge ok inline">Infos formelles principales trouvées</p>'}${p.rental_positive_signals?`<p class="help"><b>Signaux location + :</b> ${esc(p.rental_positive_signals)}</p>`:''}${p.rental_negative_signals?`<p class="help"><b>Signaux location - :</b> ${esc(p.rental_negative_signals)}</p>`:''}${p.evidence_text?`<p class="help"><b>Preuves IA :</b> ${esc(p.evidence_text.slice(0,200))}</p>`:''}</div>
    <div class="section"><h3>Enrichissement local</h3><p class="help">Ces corrections restent locales au navigateur et partent dans l’export JSON du suivi.</p><div class="detail-grid"><div><label class="field-label">Contact corrigé</label><input id="ov-contact" class="input" value="${esc(o.contactOverride||'')}" placeholder="email, téléphone, personne…"></div><div><label class="field-label">Prix corrigé</label><input id="ov-price" class="input" value="${esc(o.priceOverride||'')}" placeholder="ex: 25€/h, gratuit association…"></div><div><label class="field-label">Capacité corrigée</label><input id="ov-capacity" class="input" value="${esc(o.capacityOverride||'')}" placeholder="ex: 12 pers assises"></div><div><label class="field-label">Adresse corrigée</label><input id="ov-address" class="input" value="${esc(o.addressOverride||'')}" placeholder="adresse vérifiée"></div></div><label class="field-label">Fiabilité source</label><select id="ov-source" class="input"><option value="" ${!o.sourceReliability?'selected':''}>Non qualifiée</option><option value="reliable" ${o.sourceReliability==='reliable'?'selected':''}>Fiable</option><option value="uncertain" ${o.sourceReliability==='uncertain'?'selected':''}>À confirmer</option><option value="bad" ${o.sourceReliability==='bad'?'selected':''}>Mauvaise source</option></select><label class="field-label">Note d’enrichissement</label><textarea id="ov-note" rows="2" placeholder="Ex: contact trouvé sur page mairie 2026, prix confirmé par téléphone…">${esc(o.enrichmentNote||'')}</textarea></div>
    <div class="section"><h3>Suivi prospection</h3><label class="field-label">Statut</label><select id="detail-status" class="input">${Object.entries(STATUS).map(([k,v])=>`<option value="${k}" ${c.status===k?'selected':''}>${v}</option>`).join('')}</select><div class="detail-grid"><div><label class="field-label">Prochaine action</label><input id="next-action" class="input" value="${esc(c.nextAction||'')}" placeholder="Appeler, relancer, envoyer dossier…"></div><div><label class="field-label">Date</label><input id="next-action-date" type="date" class="input" value="${esc(c.nextActionDate||'')}"></div></div><p class="help">Astuce : filtre ensuite par statut ou tri “prochaine action”.</p></div>
    <div class="section"><h3>Ajouter une note / appel</h3><textarea id="new-note" rows="4" placeholder="Ex: appelé le standard, salle dispo mercredi soir, demander attestation RC…"></textarea><div class="detail-actions"><button class="primary-btn" id="add-note">Ajouter note</button></div><div class="note-list">${notes}</div></div>
    <div class="section"><h3>Events réalisés ici</h3><div class="detail-grid"><input id="event-date" type="date" class="input"><input id="event-label" class="input" placeholder="Nom / type d’event"></div><div class="detail-actions"><button class="primary-btn" id="add-event">Ajouter event</button></div>${events}</div></div>`;
  bindDetailEvents(id);
}
function bindDetailEvents(id){
  const c=crmFor(id);
  if(!c.overrides)c.overrides={};
  const saveOv=(key,val)=>{c.overrides[key]=val; touch(id); renderAll();};
  $('detail-status').onchange=e=>{c.status=e.target.value;touch(id);renderAll();};
  $('next-action').onchange=e=>{c.nextAction=e.target.value;touch(id);renderAll();};
  $('next-action-date').onchange=e=>{c.nextActionDate=e.target.value;touch(id);renderAll();};
  $('ov-contact').onchange=e=>saveOv('contactOverride',e.target.value.trim());
  $('ov-price').onchange=e=>saveOv('priceOverride',e.target.value.trim());
  $('ov-capacity').onchange=e=>saveOv('capacityOverride',e.target.value.trim());
  $('ov-address').onchange=e=>saveOv('addressOverride',e.target.value.trim());
  $('ov-source').onchange=e=>saveOv('sourceReliability',e.target.value);
  $('ov-note').onchange=e=>saveOv('enrichmentNote',e.target.value.trim());
  $('add-note').onclick=()=>{const t=$('new-note').value.trim(); if(!t)return; c.notes.unshift({date:new Date().toLocaleString('fr-FR'),text:t}); touch(id); renderAll();};
  $('add-event').onclick=()=>{const label=$('event-label').value.trim(); if(!label)return; c.events.unshift({date:$('event-date').value||today(),label}); c.status='used'; touch(id); renderAll();};
  $('toggle-fav').onclick=()=>{c.favorite=!c.favorite;touch(id);renderAll();};
  $('copy-contact').onclick=async()=>{const f=findFeature(id), p=displayProps(f); await copyText([p.name,p.contact,p.website].filter(Boolean).join('\n'),'Contact copié');};
  $('copy-call-script').onclick=()=>copyText(callScriptFor(findFeature(id)),'Script d’appel copié');
  $('copy-email-template').onclick=()=>copyText(emailFor(findFeature(id)),'Email copié');
  $('open-gmail-compose').onclick=()=>openGmailFor(findFeature(id));
  document.querySelectorAll('[data-del-note]').forEach(b=>b.onclick=()=>{c.notes.splice(+b.dataset.delNote,1);touch(id);renderAll();});
  document.querySelectorAll('[data-del-event]').forEach(b=>b.onclick=()=>{c.events.splice(+b.dataset.delEvent,1);touch(id);renderAll();});
}

function bindControls(){
  $('search').oninput=e=>{state.filters.q=e.target.value;renderAll();};
  $('dataset-filter').onchange=e=>{state.filters.dataset=e.target.value;renderAll();};
  $('dept-filter').onchange=e=>{state.filters.dept=e.target.value;renderAll();};
  $('status-filter').onchange=e=>{state.filters.status=e.target.value;renderAll();};
  $('quality-filter').onchange=e=>{state.filters.quality=e.target.value;renderAll();};
  $('cap-max').oninput=e=>{state.filters.capMax=e.target.value;$('cap-val').textContent=`≤${e.target.value}`;renderAll();};
  $('sort-by').onchange=e=>{state.filters.sort=e.target.value;renderAll();};
  document.querySelectorAll('[data-tag-filter]').forEach(btn=>btn.onclick=()=>{ const tag=btn.dataset.tagFilter; if(state.filters.tagFilters.has(tag)){ state.filters.tagFilters.delete(tag); btn.classList.remove('active'); } else { state.filters.tagFilters.add(tag); btn.classList.add('active'); } renderAll(); });
  $('clear-tag-filters').onclick=()=>{ state.filters.tagFilters.clear(); document.querySelectorAll('[data-tag-filter]').forEach(btn=>btn.classList.remove('active')); renderAll(); };
  document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>{
    state.view=b.dataset.view;
    document.querySelectorAll('[data-view]').forEach(x=>x.classList.toggle('active',x===b));
    $('map').classList.toggle('hidden',state.view!=='map');
    $('table-view').classList.toggle('hidden',state.view!=='list');
    $('pipeline-view').classList.toggle('hidden',state.view!=='pipeline');
    $('funnel-view').classList.toggle('hidden',state.view!=='funnel');
    setTimeout(()=>map.invalidateSize(),80);
  });
  $('close-detail').onclick=()=>$('detail-panel').classList.add('hidden');
  $('open-sidebar').onclick=()=>$('sidebar').classList.add('open');
  $('toggle-sidebar').onclick=()=>$('sidebar').classList.remove('open');
  $('funnel-stage-filter').onchange=()=>renderFunnel();
  $('funnel-source-filter').onchange=()=>renderFunnel();
  $('export-json').onclick=()=>{const blob=new Blob([JSON.stringify({exportedAt:new Date().toISOString(),crm:state.crm},null,2)],{type:'application/json'}); const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download=`salles-idf-suivi-${today()}.json`; a.click(); URL.revokeObjectURL(a.href);};
  $('import-json').onchange=e=>{const file=e.target.files[0]; if(!file)return; const r=new FileReader(); r.onload=()=>{try{const obj=JSON.parse(r.result); state.crm=obj.crm||obj; saveCrm(); toast('Suivi importé'); renderAll();}catch{toast('Import impossible');}}; r.readAsText(file);};
}

Promise.all([
  fetch('salles_all_idf.geojson').then(r=>r.json()),
  fetch('import_queue.geojson').then(r=>r.ok?r.json():{type:'FeatureCollection',features:[]}).catch(()=>({type:'FeatureCollection',features:[]})),
  fetch('funnel_debug.json').then(r=>r.ok?r.json():{items:[],stage_counts:{}}).catch(()=>({items:[],stage_counts:{}}))
]).then(([venues,candidates,funnelData])=>{
  venues.features=(venues.features||[]).map(f=>{ f.properties={...(f.properties||{}), _dataset:'venue'}; return f; });
  candidates.features=(candidates.features||[]).map(f=>{ const p=f.properties||{}; f.properties={...p, _dataset:'candidate', name:p.name||p.raw_name||'Candidat sans nom', fit_score:p.fit_beyond_score||p.fit_score||0, price_score:p.actionability_score||p.price_score||0}; return f; });
  state.venues=venues;
  state.candidates=candidates;
  state.data={type:'FeatureCollection', features:[...venues.features, ...candidates.features]};
  state.funnelItems=funnelData.items||[];
  state.funnelStageCounts=funnelData.stage_counts||{};
  loadCrm(); buildQuality(); bindControls(); renderAll();
  const mapped=state.filtered.map(coordsOf).filter(Boolean);
  if(mapped.length){ const bounds=L.latLngBounds(mapped); map.fitBounds(bounds.pad(.08)); }
}).catch(err=>{
  console.error('Erreur chargement données', err);
  toast('Erreur chargement données — voir console');
});
