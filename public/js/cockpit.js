(() => {
  'use strict';

  const CONFIG = window.SALLES_CONFIG || {};
  const STATUS = Object.freeze({
    to_call: 'À appeler',
    callback: 'À rappeler',
    available: 'Disponible',
    unavailable: 'Indisponible',
    needs_confirmation: 'À confirmer'
  });
  const TEAM_STATUSES = new Set(['available', 'needs_confirmation', 'callback']);
  const CALLABLE_STATUSES = new Set(['to_call', 'callback']);
  const LEASE_MS = 20 * 60 * 1000;
  const POLL_MS = 10_000;

  const state = {
    manifest: null,
    features: [],
    featuresById: new Map(),
    privateById: new Map(),
    followups: new Map(),
    activities: [],
    members: new Map(),
    campaign: null,
    member: null,
    user: null,
    client: null,
    channel: null,
    pollTimer: null,
    lastSyncAt: 0,
    privateReady: false,
    syncMode: 'public',
    selectedId: null,
    currentView: 'map',
    map: null,
    markerLayer: null,
    markersById: new Map(),
    pendingPhoneVenueId: null,
    toastTimer: null,
    bootingShared: false
  };

  const byId = (id) => document.getElementById(id);
  const text = (value) => String(value ?? '').trim();

  function element(tag, options = {}, children = []) {
    const node = document.createElement(tag);
    if (options.className) node.className = options.className;
    if (options.text !== undefined) node.textContent = text(options.text);
    if (options.type) node.type = options.type;
    if (options.id) node.id = options.id;
    if (options.name) node.name = options.name;
    if (options.value !== undefined) node.value = options.value;
    if (options.placeholder) node.placeholder = options.placeholder;
    if (options.required) node.required = true;
    if (options.disabled) node.disabled = true;
    if (options.hidden) node.classList.add('hidden');
    for (const child of children) {
      if (child) node.append(child);
    }
    return node;
  }

  function option(value, label, selected = false) {
    const node = element('option', { value, text: label });
    node.selected = selected;
    return node;
  }

  function showBanner(message, kind = 'info') {
    const banner = byId('app-banner');
    banner.textContent = message;
    banner.className = `banner ${kind}`;
  }

  function setSyncMode(mode, message) {
    state.syncMode = mode;
    const badge = byId('sync-badge');
    const definitions = {
      public: ['Catalogue public', 'neutral'],
      connecting: ['Connexion…', 'callback'],
      realtime: ['Synchronisé', 'available'],
      polling: ['Sync dégradée', 'callback'],
      read_only: ['Lecture seule', 'unavailable']
    };
    const [label, className] = definitions[mode] || definitions.public;
    badge.textContent = label;
    badge.className = `status-badge ${className}`;
    if (message) showBanner(message, mode === 'realtime' ? 'success' : mode === 'read_only' ? 'warning' : 'info');
  }

  function toast(message) {
    const node = byId('toast');
    node.textContent = message;
    node.classList.add('visible');
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => node.classList.remove('visible'), 2600);
  }

  function friendlyError(error) {
    const code = error?.code || error?.message || 'UNKNOWN';
    const messages = {
      FORBIDDEN: 'Ce compte n’est pas autorisé pour cette action.',
      CAMPAIGN_NOT_ACTIVE: 'La campagne a changé. Actualisation nécessaire.',
      CLAIMED_BY_OTHER: 'Cette salle vient d’être prise par un autre membre.',
      STALE_CLAIM_CONFIRM_REQUIRED: 'Le bail a changé. Recharge la salle avant de la reprendre.',
      NOT_CLAIM_OWNER: 'Tu ne détiens plus cet appel.',
      FIELD_CONFLICT: 'Cette information a été modifiée ailleurs. La fiche va être rechargée.',
      VALIDATION_ERROR: 'Vérifie les informations saisies.',
      NOT_FOUND: 'Cette salle n’existe plus dans la campagne.',
      OPERATION_ID_REUSED: 'La requête a déjà été utilisée avec un autre contenu.',
      CLIENT_INCOMPATIBLE: 'Le site est en cours de mise à jour. Consultation uniquement.'
    };
    return messages[code] || 'Une erreur empêche l’enregistrement. Réessaie après actualisation.';
  }

  function statusOf(venueId) {
    return state.followups.get(venueId)?.status || 'to_call';
  }

  function followupOf(venueId) {
    return state.followups.get(venueId) || {
      campaign_id: state.campaign?.id || null,
      venue_id: venueId,
      is_shortlisted: false,
      assignee_id: null,
      status: 'to_call',
      availability_text: null,
      confirmed_price_text: null,
      next_action_at: null,
      claimed_by: null,
      claim_expires_at: null,
      version: 0
    };
  }

  function applyCampaignVenue(row) {
    if (!row?.venue_id) return;
    const existing = state.followups.get(row.venue_id);
    if (!existing || Number(row.version || 0) >= Number(existing.version || 0)) {
      state.followups.set(row.venue_id, row);
    }
  }

  function memberName(userId) {
    if (!userId) return 'Non attribuée';
    return state.members.get(userId)?.display_name || 'Membre';
  }

  function isLeaseActive(followup) {
    return Boolean(followup.claimed_by && followup.claim_expires_at && new Date(followup.claim_expires_at).getTime() > Date.now());
  }

  function isOwnLease(followup) {
    return isLeaseActive(followup) && followup.claimed_by === state.user?.id;
  }

  function canMutate() {
    if (!state.user || !state.campaign || !state.privateReady) return false;
    if (state.syncMode === 'realtime') return true;
    return state.syncMode === 'polling' && Date.now() - state.lastSyncAt < 15_000;
  }

  function privateDetails(venueId) {
    return state.privateById.get(venueId) || null;
  }

  function venueSearchText(feature) {
    const props = feature.properties || {};
    const details = privateDetails(props.id) || {};
    return [
      props.name, props.city, props.department, props.address, props.category,
      props.capacity_text, props.price_text, details.contact, details.website,
      details.pros, details.cons
    ].map(text).join(' ').toLocaleLowerCase('fr');
  }

  function filteredFeatures() {
    const query = text(byId('search-input').value).toLocaleLowerCase('fr');
    const department = byId('department-filter').value;
    const status = byId('status-filter').value;
    return state.features.filter((feature) => {
      const props = feature.properties || {};
      const followup = followupOf(props.id);
      if (department !== 'all' && text(props.department) !== department) return false;
      if (status === 'shortlisted' && !followup.is_shortlisted) return false;
      if (status !== 'all' && status !== 'shortlisted' && followup.status !== status) return false;
      return !query || venueSearchText(feature).includes(query);
    }).sort((a, b) => {
      const aFollowup = followupOf(a.properties.id);
      const bFollowup = followupOf(b.properties.id);
      if (aFollowup.is_shortlisted !== bFollowup.is_shortlisted) return aFollowup.is_shortlisted ? -1 : 1;
      const aFit = Number(privateDetails(a.properties.id)?.fit_score || 0);
      const bFit = Number(privateDetails(b.properties.id)?.fit_score || 0);
      if (aFit !== bFit) return bFit - aFit;
      return text(a.properties.name).localeCompare(text(b.properties.name), 'fr');
    });
  }

  async function sha256Hex(buffer) {
    const hash = await crypto.subtle.digest('SHA-256', buffer);
    return Array.from(new Uint8Array(hash)).map((byte) => byte.toString(16).padStart(2, '0')).join('');
  }

  async function fetchVerifiedJson(path, expectedHash = null) {
    const response = await fetch(path, { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP_${response.status}:${path}`);
    const buffer = await response.arrayBuffer();
    if (expectedHash && await sha256Hex(buffer) !== expectedHash) throw new Error(`CHECKSUM:${path}`);
    return JSON.parse(new TextDecoder().decode(buffer));
  }

  async function loadPublicCatalog() {
    state.manifest = await fetchVerifiedJson('dataset-manifest.json');
    const catalogArtifact = state.manifest.artifacts?.find((item) => item.path === 'salles_catalog_public.geojson');
    if (!catalogArtifact) throw new Error('MANIFEST_CATALOG_MISSING');
    const catalog = await fetchVerifiedJson(catalogArtifact.path, catalogArtifact.sha256);
    if (catalog.type !== 'FeatureCollection' || !Array.isArray(catalog.features) || !catalog.features.length) {
      throw new Error('CATALOG_INVALID');
    }
    if (catalog.release_id !== state.manifest.release_id) throw new Error('RELEASE_MISMATCH');
    state.features = catalog.features;
    state.featuresById = new Map(catalog.features.map((feature) => [feature.properties.id, feature]));
    byId('catalog-count').textContent = `${catalog.features.length} pistes qualifiées`;
  }

  function initMap() {
    if (!window.L) {
      byId('map').replaceChildren(element('p', { className: 'empty-state', text: 'Carte indisponible. Utilise la liste.' }));
      return;
    }
    state.map = L.map('map', { zoomControl: true }).setView([48.8566, 2.3522], 10);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap'
    }).addTo(state.map);
    state.markerLayer = L.layerGroup().addTo(state.map);
    renderMap();
  }

  function markerColor(status) {
    return {
      to_call: '#2d62a3',
      callback: '#b86c08',
      available: '#0c6b4f',
      unavailable: '#a13932',
      needs_confirmation: '#887026'
    }[status] || '#66736a';
  }

  function renderMap() {
    if (!state.map || !state.markerLayer) return;
    state.markerLayer.clearLayers();
    state.markersById.clear();
    const bounds = [];
    for (const feature of filteredFeatures()) {
      const coordinates = feature.geometry?.coordinates;
      if (!Array.isArray(coordinates) || coordinates.length < 2) continue;
      const lon = Number(coordinates[0]);
      const lat = Number(coordinates[1]);
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;
      const venueId = feature.properties.id;
      const status = statusOf(venueId);
      const marker = L.circleMarker([lat, lon], {
        radius: followupOf(venueId).is_shortlisted ? 8 : 6,
        color: '#fff',
        weight: 2,
        fillColor: markerColor(status),
        fillOpacity: .9
      });
      marker.bindTooltip(text(feature.properties.name), { direction: 'top' });
      marker.on('click', () => openDetail(venueId));
      marker.addTo(state.markerLayer);
      state.markersById.set(venueId, marker);
      bounds.push([lat, lon]);
    }
    if (bounds.length && !state.selectedId) state.map.fitBounds(bounds, { padding: [24, 24], maxZoom: 12 });
  }

  function badge(status) {
    return element('span', { className: `mini-chip ${status}`, text: STATUS[status] || status });
  }

  function renderVenueList() {
    const venues = filteredFeatures();
    const list = byId('venue-list');
    const fragment = document.createDocumentFragment();
    for (const feature of venues) {
      const props = feature.properties;
      const followup = followupOf(props.id);
      const button = element('button', {
        className: `venue-card${state.selectedId === props.id ? ' selected' : ''}`,
        type: 'button'
      });
      const title = element('h3', { text: props.name });
      const location = element('p', { text: [props.city, props.department, props.capacity_text].filter(Boolean).join(' · ') });
      const meta = element('div', { className: 'card-meta' }, [
        badge(followup.status),
        element('span', { className: 'muted', text: followup.claimed_by ? `Pris par ${memberName(followup.claimed_by)}` : props.price_text || 'Prix à confirmer' })
      ]);
      button.append(title, location, meta);
      button.addEventListener('click', () => openDetail(props.id));
      fragment.append(button);
    }
    if (!venues.length) fragment.append(element('p', { className: 'empty-state', text: 'Aucune salle ne correspond à ces filtres.' }));
    list.replaceChildren(fragment);
    byId('filter-summary').textContent = `${venues.length} salle${venues.length > 1 ? 's' : ''} affichée${venues.length > 1 ? 's' : ''}`;
  }

  function queueFeatures() {
    return state.features.filter((feature) => {
      const followup = followupOf(feature.properties.id);
      return CALLABLE_STATUSES.has(followup.status) && (followup.is_shortlisted || followup.assignee_id || isLeaseActive(followup));
    }).sort((a, b) => {
      const aFollowup = followupOf(a.properties.id);
      const bFollowup = followupOf(b.properties.id);
      if (Boolean(aFollowup.assignee_id === state.user?.id) !== Boolean(bFollowup.assignee_id === state.user?.id)) {
        return aFollowup.assignee_id === state.user?.id ? -1 : 1;
      }
      return text(a.properties.name).localeCompare(text(b.properties.name), 'fr');
    });
  }

  function renderQueue() {
    const queue = queueFeatures();
    byId('queue-count').textContent = String(queue.length);
    const grid = byId('queue-grid');
    const fragment = document.createDocumentFragment();
    for (const feature of queue) {
      const props = feature.properties;
      const followup = followupOf(props.id);
      const card = element('article', { className: 'queue-card' });
      card.append(
        element('h3', { text: props.name }),
        element('p', { text: [props.city, props.department, props.capacity_text].filter(Boolean).join(' · ') }),
        element('p', { text: followup.assignee_id ? `Responsable : ${memberName(followup.assignee_id)}` : 'Non attribuée' }),
        badge(followup.status)
      );
      const action = element('button', {
        className: 'primary-button',
        type: 'button',
        text: isOwnLease(followup) ? 'Revenir à mon appel' : isLeaseActive(followup) ? `Pris par ${memberName(followup.claimed_by)}` : 'Ouvrir la fiche',
        disabled: isLeaseActive(followup) && !isOwnLease(followup)
      });
      action.addEventListener('click', () => openDetail(props.id));
      card.append(action);
      fragment.append(card);
    }
    if (!queue.length) fragment.append(element('p', { className: 'empty-state', text: 'Ajoute des salles à la shortlist pour préparer les appels.' }));
    grid.replaceChildren(fragment);
  }

  function renderTeam() {
    const rows = state.features.filter((feature) => TEAM_STATUSES.has(statusOf(feature.properties.id)));
    byId('team-count').textContent = String(rows.length);
    const counts = {
      available: rows.filter((feature) => statusOf(feature.properties.id) === 'available').length,
      needs_confirmation: rows.filter((feature) => statusOf(feature.properties.id) === 'needs_confirmation').length,
      callback: rows.filter((feature) => statusOf(feature.properties.id) === 'callback').length
    };
    const counterFragment = document.createDocumentFragment();
    for (const [status, label] of [['available', 'Disponibles'], ['needs_confirmation', 'À confirmer'], ['callback', 'Rappels']]) {
      counterFragment.append(element('div', { className: 'counter' }, [
        element('strong', { text: counts[status] }),
        element('span', { text: label })
      ]));
    }
    byId('team-counters').replaceChildren(counterFragment);

    const tbody = byId('team-table-body');
    const fragment = document.createDocumentFragment();
    for (const feature of rows.sort((a, b) => text(a.properties.name).localeCompare(text(b.properties.name), 'fr'))) {
      const followup = followupOf(feature.properties.id);
      const tr = element('tr');
      const values = [
        feature.properties.name,
        STATUS[followup.status],
        followup.availability_text || '—',
        followup.confirmed_price_text || '—',
        memberName(followup.assignee_id || followup.updated_by),
        followup.next_action_at ? new Date(followup.next_action_at).toLocaleString('fr-FR') : '—'
      ];
      for (const value of values) tr.append(element('td', { text: value }));
      tr.addEventListener('click', () => openDetail(feature.properties.id));
      fragment.append(tr);
    }
    tbody.replaceChildren(fragment);
    byId('team-empty').classList.toggle('hidden', rows.length > 0);
  }

  function renderAll() {
    renderAuth();
    renderVenueList();
    renderMap();
    renderQueue();
    renderTeam();
    if (state.selectedId && byId('detail-dialog').open) renderDetail(state.selectedId);
  }

  function renderAuth() {
    const panel = byId('auth-panel');
    const form = byId('login-form');
    const memberChip = byId('member-chip');
    const signout = byId('signout-button');
    const sharedConfigured = CONFIG.mode === 'shared' && CONFIG.supabaseUrl && CONFIG.supabaseAnonKey && window.supabase?.createClient;
    if (state.user) {
      panel.classList.add('hidden');
      memberChip.textContent = state.member?.display_name || state.user.email || 'Membre';
      memberChip.classList.remove('hidden');
      signout.classList.remove('hidden');
    } else {
      panel.classList.remove('hidden');
      memberChip.classList.add('hidden');
      signout.classList.add('hidden');
      form.classList.toggle('hidden', !sharedConfigured);
      if (!sharedConfigured) {
        byId('auth-copy').querySelector('p:last-child').textContent = 'Le catalogue public est disponible. La collaboration sera activée dès que Supabase sera configuré.';
      }
    }
    byId('campaign-label').textContent = state.campaign?.name || 'Cockpit d’appels';
  }

  function dataBlock(label, value) {
    const dl = element('dl', { className: 'data-block' });
    dl.append(element('dt', { text: label }), element('dd', { text: value || '—' }));
    return dl;
  }

  function section(title) {
    const node = element('section', { className: 'detail-section' });
    if (title) node.append(element('h3', { text: title }));
    return node;
  }

  function safeExternalLink(label, rawUrl, className = 'secondary-button') {
    if (!rawUrl) return null;
    try {
      const url = new URL(rawUrl);
      if (!['https:', 'http:'].includes(url.protocol)) return null;
      const link = element('a', { className, text: label });
      link.href = url.href;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      return link;
    } catch {
      return null;
    }
  }

  function extractPhone(contact) {
    const match = text(contact).match(/(?:\+33|0)[1-9](?:[ .-]?\d{2}){4}/);
    if (!match) return null;
    const display = match[0];
    const normalized = display.replace(/[ .-]/g, '');
    return { display, href: `tel:${normalized}` };
  }

  function operationId() {
    return crypto.randomUUID();
  }

  async function callRpc(name, args) {
    if (!canMutate() && name !== 'get_workspace_bootstrap') {
      const error = new Error('READ_ONLY');
      error.code = 'READ_ONLY';
      throw error;
    }
    const { data, error } = await state.client.rpc(name, args);
    if (error) throw error;
    if (!data?.ok) {
      const businessError = new Error(data?.code || 'RPC_ERROR');
      businessError.code = data?.code || 'RPC_ERROR';
      businessError.payload = data;
      throw businessError;
    }
    const row = data.campaignVenue || data.campaign_venue;
    if (row) applyCampaignVenue(row);
    return data;
  }

  async function runAction(button, action, successMessage) {
    button.disabled = true;
    const original = button.textContent;
    button.textContent = 'Enregistrement…';
    try {
      const result = await action();
      if (successMessage) toast(successMessage);
      renderAll();
      return result;
    } catch (error) {
      console.error({ code: error?.code || error?.message, release: CONFIG.appRelease });
      toast(friendlyError(error));
      await loadSnapshot().catch(() => {});
      renderAll();
      return null;
    } finally {
      button.disabled = false;
      button.textContent = original;
    }
  }

  function renderAssignment(container, venueId, followup) {
    const wrapper = element('div', { className: 'field' });
    const label = element('label', { text: 'Responsable' });
    const select = element('select', { disabled: !canMutate() || isLeaseActive(followup) });
    select.append(option('', 'Non attribuée', !followup.assignee_id));
    for (const member of state.members.values()) {
      select.append(option(member.user_id, member.display_name, member.user_id === followup.assignee_id));
    }
    select.addEventListener('change', async () => {
      const previous = followup.assignee_id;
      const next = select.value || null;
      select.disabled = true;
      try {
        await callRpc('update_followup_field', {
          p_operation_id: operationId(),
          p_campaign_id: state.campaign.id,
          p_venue_id: venueId,
          p_field_name: 'assignee_id',
          p_expected_old_value: previous,
          p_new_value: next,
          p_note: 'Attribution depuis la fiche'
        });
        toast('Responsable mis à jour');
      } catch (error) {
        toast(friendlyError(error));
        await loadSnapshot().catch(() => {});
      }
      renderAll();
    });
    wrapper.append(label, select);
    container.append(wrapper);
  }

  function renderClaimSection(container, venueId, followup, details) {
    const lease = section('Appel');
    const active = isLeaseActive(followup);
    const own = isOwnLease(followup);

    if (active && !own) {
      const box = element('div', { className: 'lease-box other' });
      box.append(
        element('strong', { text: `Appel pris par ${memberName(followup.claimed_by)}` }),
        element('p', { className: 'help', text: `Bail jusqu’à ${new Date(followup.claim_expires_at).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}.` })
      );
      lease.append(box);
    } else if (own) {
      const box = element('div', { className: 'lease-box' });
      const leaseLine = element('div', { className: 'lease-line' }, [
        element('p', { text: `Appel réservé jusqu’à ${new Date(followup.claim_expires_at).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}` }),
        badge(followup.status)
      ]);
      box.append(leaseLine);
      const actions = element('div', { className: 'action-row' });
      const phone = extractPhone(details?.contact);
      if (phone) {
        const callLink = element('a', { className: 'primary-button', text: `Appeler ${phone.display}` });
        callLink.href = phone.href;
        callLink.addEventListener('click', () => { state.pendingPhoneVenueId = venueId; });
        actions.append(callLink);
      } else {
        actions.append(element('p', { className: 'help', text: 'Aucun numéro exploitable. Utilise le contact ou le site.' }));
      }
      const release = element('button', { className: 'secondary-button', type: 'button', text: 'Libérer la salle' });
      release.addEventListener('click', () => runAction(release, () => callRpc('release_claim', {
        p_operation_id: operationId(), p_campaign_id: state.campaign.id, p_venue_id: venueId
      }), 'Salle libérée'));
      actions.append(release);
      box.append(actions);
      lease.append(box);
      renderResultForm(lease, venueId, followup, 'complete_call');
    } else if (CALLABLE_STATUSES.has(followup.status)) {
      const expired = Boolean(followup.claimed_by && followup.claim_expires_at);
      const claimButton = element('button', {
        className: 'primary-button',
        type: 'button',
        text: expired ? 'Reprendre cette salle' : 'Prendre cette salle',
        disabled: !canMutate()
      });
      claimButton.addEventListener('click', () => runAction(claimButton, async () => {
        if (expired) {
          return callRpc('take_over_stale_claim', {
            p_operation_id: operationId(),
            p_campaign_id: state.campaign.id,
            p_venue_id: venueId,
            p_observed_claimed_by: followup.claimed_by,
            p_observed_expiry: followup.claim_expires_at
          });
        }
        return callRpc('claim_venue', {
          p_operation_id: operationId(), p_campaign_id: state.campaign.id, p_venue_id: venueId
        });
      }, expired ? 'Salle reprise' : 'Salle réservée pour ton appel'));
      lease.append(
        element('p', { className: 'help', text: 'Le contact et le bouton téléphone apparaissent après confirmation de la réservation.' }),
        claimButton
      );
    } else {
      lease.append(element('p', { className: 'help', text: 'Un résultat est déjà enregistré. Tu peux le corriger avec une note explicative.' }));
      renderResultForm(lease, venueId, followup, 'correct_call_result');
    }
    container.append(lease);
  }

  function renderResultForm(container, venueId, followup, rpcName) {
    const form = element('form', { className: 'form-grid' });
    const statusField = element('div', { className: 'field' });
    const statusSelect = element('select', { required: true });
    for (const status of ['available', 'unavailable', 'callback', 'needs_confirmation']) {
      statusSelect.append(option(status, STATUS[status], followup.status === status));
    }
    statusField.append(element('label', { text: 'Résultat' }), statusSelect);

    const availabilityField = element('div', { className: 'field' });
    const availability = element('input', { value: followup.availability_text || '', placeholder: 'Ex. mardi soir disponible' });
    availabilityField.append(element('label', { text: 'Disponibilité' }), availability);

    const priceField = element('div', { className: 'field' });
    const price = element('input', { value: followup.confirmed_price_text || '', placeholder: 'Ex. 180 € TTC / jour' });
    priceField.append(element('label', { text: 'Prix confirmé' }), price);

    const nextField = element('div', { className: 'field' });
    const nextAction = element('input');
    nextAction.type = 'datetime-local';
    if (followup.next_action_at) {
      const date = new Date(followup.next_action_at);
      nextAction.value = new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
    }
    nextField.append(element('label', { text: 'Date du rappel' }), nextAction);

    const noteField = element('div', { className: 'field span-2' });
    const note = element('textarea', { required: true, placeholder: 'Compte rendu factuel de l’appel…' });
    note.maxLength = 2000;
    noteField.append(
      element('label', { text: rpcName === 'complete_call' ? 'Note d’appel' : 'Motif de la correction' }),
      note,
      element('span', { className: 'help', text: 'Aucune donnée sensible, jugement personnel ou information privée inutile.' })
    );

    const toggleNextAction = () => {
      const isCallback = statusSelect.value === 'callback';
      nextField.classList.toggle('hidden', !isCallback);
      nextAction.required = isCallback;
      if (!isCallback) nextAction.value = '';
    };
    statusSelect.addEventListener('change', toggleNextAction);
    toggleNextAction();

    const submit = element('button', {
      className: 'primary-button span-2',
      type: 'submit',
      text: rpcName === 'complete_call' ? 'Enregistrer le résultat' : 'Corriger le résultat',
      disabled: !canMutate()
    });
    form.append(statusField, availabilityField, priceField, nextField, noteField, submit);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (statusSelect.value === 'callback' && !nextAction.value) {
        toast('Ajoute la date du rappel.');
        return;
      }
      await runAction(submit, () => callRpc(rpcName, {
        p_operation_id: operationId(),
        p_campaign_id: state.campaign.id,
        p_venue_id: venueId,
        p_result_status: statusSelect.value,
        p_availability_text: text(availability.value) || null,
        p_confirmed_price_text: text(price.value) || null,
        p_next_action_at: nextAction.value ? new Date(nextAction.value).toISOString() : null,
        p_note: text(note.value)
      }), 'Résultat partagé avec l’équipe');
    });
    container.append(form);
  }

  function renderHistory(container, venueId) {
    const history = section('Historique récent');
    const activities = state.activities.filter((item) => item.venue_id === venueId).slice(0, 12);
    const list = element('div', { className: 'history-list' });
    if (!activities.length) {
      list.append(element('p', { className: 'help', text: 'Aucune activité pour cette salle.' }));
    } else {
      for (const activity of activities) {
        const body = activity.note || `${activity.field_name || activity.activity_type} mis à jour`;
        list.append(element('div', { className: 'history-item' }, [
          element('time', { text: `${new Date(activity.created_at).toLocaleString('fr-FR')} · ${memberName(activity.created_by)}` }),
          element('strong', { text: activity.activity_type.replaceAll('_', ' ') }),
          element('div', { text: body })
        ]));
      }
    }
    history.append(list);
    container.append(history);
  }

  function renderDetail(venueId) {
    const feature = state.featuresById.get(venueId);
    if (!feature) return;
    const props = feature.properties;
    const details = privateDetails(venueId);
    const followup = followupOf(venueId);
    byId('detail-eyebrow').textContent = [props.city, props.department].filter(Boolean).join(' · ');
    byId('detail-title').textContent = props.name;
    const content = byId('detail-content');
    const fragment = document.createDocumentFragment();

    const overview = section();
    const grid = element('div', { className: 'detail-grid' }, [
      dataBlock('Adresse', props.address),
      dataBlock('Capacité', props.capacity_text),
      dataBlock('Prix indicatif', props.price_text),
      dataBlock('Catégorie', props.category)
    ]);
    overview.append(grid);
    const publicActions = element('div', { className: 'action-row' });
    const coordinates = feature.geometry?.coordinates;
    if (Array.isArray(coordinates) && coordinates.length >= 2) {
      publicActions.append(safeExternalLink('Itinéraire', `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(`${coordinates[1]},${coordinates[0]}`)}`));
    }
    overview.append(publicActions);
    fragment.append(overview);

    if (!state.user) {
      const locked = section('Espace équipe');
      locked.append(element('p', { className: 'help', text: 'Connecte-toi pour voir le contact, ajouter cette salle à la shortlist et partager un appel.' }));
      fragment.append(locked);
    } else if (!state.privateReady || !details) {
      const unavailable = section('Détails privés indisponibles');
      unavailable.append(element('p', { className: 'help', text: 'Le catalogue public reste visible, mais les contacts ne sont pas chargés. Aucune écriture n’est autorisée.' }));
      fragment.append(unavailable);
    } else {
      const coordination = section('Préparation équipe');
      const prepGrid = element('div', { className: 'form-grid' });
      const shortlistButton = element('button', {
        className: followup.is_shortlisted ? 'secondary-button' : 'primary-button',
        type: 'button',
        text: followup.is_shortlisted ? 'Retirer de la shortlist' : 'Ajouter à la shortlist',
        disabled: !canMutate()
      });
      shortlistButton.addEventListener('click', () => runAction(shortlistButton, () => callRpc('update_followup_field', {
        p_operation_id: operationId(),
        p_campaign_id: state.campaign.id,
        p_venue_id: venueId,
        p_field_name: 'is_shortlisted',
        p_expected_old_value: followup.is_shortlisted,
        p_new_value: !followup.is_shortlisted,
        p_note: null
      }), followup.is_shortlisted ? 'Salle retirée de la shortlist' : 'Salle ajoutée à la shortlist'));
      prepGrid.append(shortlistButton);
      renderAssignment(prepGrid, venueId, followup);
      coordination.append(prepGrid);
      fragment.append(coordination);

      renderClaimSection(fragment, venueId, followup, details);

      const contact = section(isOwnLease(followup) ? 'Contact de la salle' : 'Contact protégé');
      if (isOwnLease(followup)) {
        contact.append(element('div', { className: 'detail-grid' }, [
          dataBlock('Contact', details.contact),
          dataBlock('Confiance', details.confidence)
        ]));
        const actions = element('div', { className: 'action-row' });
        actions.append(safeExternalLink('Site de la salle', details.website));
        actions.append(safeExternalLink('Source', details.source_url));
        contact.append(actions);
      } else {
        contact.append(element('p', { className: 'help', text: 'Le contact direct apparaît uniquement après avoir pris cette salle.' }));
      }
      fragment.append(contact);

      const noteSection = section('Ajouter une note');
      const noteForm = element('form', { className: 'form-grid' });
      const note = element('textarea', { className: 'span-2', required: true, placeholder: 'Information factuelle utile à l’équipe…' });
      note.maxLength = 2000;
      const add = element('button', { className: 'secondary-button span-2', type: 'submit', text: 'Ajouter la note', disabled: !canMutate() });
      noteForm.append(note, add);
      noteForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        if (!text(note.value)) return;
        const result = await runAction(add, () => callRpc('add_note', {
          p_operation_id: operationId(), p_campaign_id: state.campaign.id, p_venue_id: venueId, p_note: text(note.value)
        }), 'Note partagée');
        if (result) note.value = '';
      });
      noteSection.append(noteForm);
      fragment.append(noteSection);
      renderHistory(fragment, venueId);
    }
    content.replaceChildren(fragment);
  }

  function openDetail(venueId) {
    state.selectedId = venueId;
    renderDetail(venueId);
    const dialog = byId('detail-dialog');
    if (!dialog.open) dialog.showModal();
    byId('sidebar').classList.remove('open');
    renderVenueList();
    const marker = state.markersById.get(venueId);
    if (marker && state.map) state.map.panTo(marker.getLatLng());
  }

  async function copyText(value) {
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      const textarea = element('textarea', { value });
      document.body.append(textarea);
      textarea.select();
      document.execCommand('copy');
      textarea.remove();
    }
  }

  async function copyTeamSummary() {
    const rows = state.features.filter((feature) => TEAM_STATUSES.has(statusOf(feature.properties.id)));
    const lines = [
      `Point d’équipe — ${state.campaign?.name || 'Salles IDF'}`,
      `Mis à jour le ${new Date().toLocaleString('fr-FR')}`,
      ''
    ];
    for (const feature of rows) {
      const followup = followupOf(feature.properties.id);
      lines.push(`- ${feature.properties.name} — ${STATUS[followup.status]} — ${followup.availability_text || 'disponibilité non précisée'} — ${followup.confirmed_price_text || 'prix non confirmé'} — ${memberName(followup.assignee_id || followup.updated_by)}`);
    }
    if (!rows.length) lines.push('Aucun résultat exploitable pour le moment.');
    await copyText(lines.join('\n'));
    toast('Résumé copié');
  }

  async function loadPrivateRelease() {
    const privateManifest = state.campaign?.private_manifest;
    if (!privateManifest || privateManifest.release_id !== state.campaign.dataset_release_id) throw new Error('PRIVATE_MANIFEST_MISSING');
    if (privateManifest.dataset_checksum !== state.campaign.dataset_manifest_checksum) throw new Error('PRIVATE_CHECKSUM_MISMATCH');
    const requiredArtifacts = (privateManifest.artifacts || []).filter((item) => item.required);
    const overlayArtifact = requiredArtifacts.find((item) => item.path.endsWith('/venue_private_details.json'));
    if (!overlayArtifact) throw new Error('PRIVATE_OVERLAY_MISSING');

    let overlay = null;
    for (const artifact of requiredArtifacts) {
      const { data: blob, error } = await state.client.storage.from(CONFIG.privateBucket || 'venue-datasets').download(artifact.path);
      if (error) throw error;
      const buffer = await blob.arrayBuffer();
      if (await sha256Hex(buffer) !== artifact.sha256) throw new Error(`PRIVATE_ARTIFACT_CHECKSUM:${artifact.path}`);
      if (artifact === overlayArtifact) overlay = JSON.parse(new TextDecoder().decode(buffer));
    }
    if (!overlay || overlay.release_id !== state.campaign.dataset_release_id || overlay.dataset_checksum !== state.campaign.dataset_manifest_checksum) {
      throw new Error('PRIVATE_RELEASE_MISMATCH');
    }
    const map = new Map((overlay.venues || []).map((venue) => [venue.id, venue]));
    if (map.size !== state.features.length || state.features.some((feature) => !map.has(feature.properties.id))) {
      throw new Error('PRIVATE_ID_MISMATCH');
    }
    state.privateById = map;
    state.privateReady = true;
  }

  async function loadSnapshot() {
    if (!state.client || !state.campaign) return;
    const [followupsResult, activitiesResult] = await Promise.all([
      state.client.from('campaign_venues').select('*').eq('campaign_id', state.campaign.id),
      state.client.from('venue_activities').select('*').eq('campaign_id', state.campaign.id).order('created_at', { ascending: false }).limit(100)
    ]);
    if (followupsResult.error) throw followupsResult.error;
    if (activitiesResult.error) throw activitiesResult.error;
    state.followups = new Map((followupsResult.data || []).map((row) => [row.venue_id, row]));
    state.activities = activitiesResult.data || [];
    state.lastSyncAt = Date.now();
    renderAll();
  }

  function stopPolling() {
    if (state.pollTimer) clearInterval(state.pollTimer);
    state.pollTimer = null;
  }

  function startPolling() {
    if (state.pollTimer || !state.user) return;
    setSyncMode('polling', 'Synchronisation dégradée : actualisation toutes les 10 secondes.');
    state.pollTimer = setInterval(async () => {
      try {
        await loadSnapshot();
      } catch {
        if (Date.now() - state.lastSyncAt > 15_000) setSyncMode('read_only', 'Synchronisation indisponible — consultation uniquement.');
      }
    }, POLL_MS);
  }

  async function setupRealtime() {
    if (state.channel) await state.client.removeChannel(state.channel);
    const campaignId = state.campaign.id;
    state.channel = state.client.channel(`campaign-${campaignId}`)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'campaign_venues', filter: `campaign_id=eq.${campaignId}` }, (payload) => {
        if (payload.new?.venue_id) applyCampaignVenue(payload.new);
        state.lastSyncAt = Date.now();
        renderAll();
      })
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'venue_activities', filter: `campaign_id=eq.${campaignId}` }, (payload) => {
        if (payload.new?.id && !state.activities.some((item) => item.id === payload.new.id)) {
          state.activities.unshift(payload.new);
          state.activities = state.activities.slice(0, 200);
        }
        state.lastSyncAt = Date.now();
        renderAll();
      })
      .subscribe(async (status) => {
        if (status === 'SUBSCRIBED') {
          stopPolling();
          await loadSnapshot().catch(() => {});
          setSyncMode('realtime', 'Cockpit synchronisé avec l’équipe.');
        } else if (['CHANNEL_ERROR', 'TIMED_OUT', 'CLOSED'].includes(status)) {
          startPolling();
        }
      });
  }

  async function bootstrapShared() {
    if (!state.client || !state.user || state.bootingShared) return;
    state.bootingShared = true;
    setSyncMode('connecting', 'Connexion à l’espace partagé…');
    try {
      const { data, error } = await state.client.rpc('get_workspace_bootstrap', {
        p_client_contract_version: Number(CONFIG.clientContractVersion || 1)
      });
      if (error) throw error;
      if (!data?.ok) {
        const businessError = new Error(data?.code || 'BOOTSTRAP_FAILED');
        businessError.code = data?.code;
        throw businessError;
      }
      state.member = data.member;
      state.campaign = data.campaign;
      state.members = new Map((data.members || []).map((member) => [member.user_id, member]));
      if (state.campaign.dataset_release_id !== state.manifest.release_id || state.campaign.dataset_manifest_checksum !== state.manifest.dataset_checksum) {
        throw new Error('PUBLIC_PRIVATE_RELEASE_MISMATCH');
      }
      await loadPrivateRelease();
      await loadSnapshot();
      await setupRealtime();
      renderAll();
    } catch (error) {
      console.error({ code: error?.code || error?.message, release: CONFIG.appRelease });
      state.privateReady = false;
      setSyncMode('read_only', error?.code === 'FORBIDDEN' ? 'Ce compte n’est pas autorisé pour cet espace.' : 'Collaboration indisponible — catalogue public uniquement.');
      renderAll();
    } finally {
      state.bootingShared = false;
    }
  }

  function clearSharedState() {
    stopPolling();
    if (state.channel && state.client) state.client.removeChannel(state.channel).catch(() => {});
    state.channel = null;
    state.user = null;
    state.member = null;
    state.campaign = null;
    state.privateReady = false;
    state.privateById.clear();
    state.followups.clear();
    state.activities = [];
    state.members.clear();
    setSyncMode('public', 'Catalogue public — connecte-toi pour collaborer.');
    renderAll();
  }

  async function initSupabase() {
    const configured = CONFIG.mode === 'shared' && CONFIG.supabaseUrl && CONFIG.supabaseAnonKey && window.supabase?.createClient;
    if (!configured) {
      setSyncMode('read_only', 'Catalogue public disponible — collaboration non configurée.');
      renderAuth();
      return;
    }
    state.client = window.supabase.createClient(CONFIG.supabaseUrl, CONFIG.supabaseAnonKey, {
      auth: {
        storage: window.sessionStorage,
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: false
      }
    });
    state.client.auth.onAuthStateChange((event, session) => {
      if (event === 'SIGNED_OUT' || !session) {
        clearSharedState();
        return;
      }
      state.user = session.user;
      if (['SIGNED_IN', 'INITIAL_SESSION', 'TOKEN_REFRESHED'].includes(event) && !state.campaign) {
        setTimeout(() => bootstrapShared(), 0);
      }
      renderAuth();
    });
    const { data } = await state.client.auth.getSession();
    if (data.session) {
      state.user = data.session.user;
      await bootstrapShared();
    } else {
      setSyncMode('public', 'Catalogue public — connecte-toi pour collaborer.');
      renderAuth();
    }
  }

  function bindEvents() {
    byId('search-input').addEventListener('input', renderAll);
    byId('department-filter').addEventListener('change', renderAll);
    byId('status-filter').addEventListener('change', renderAll);
    byId('menu-button').addEventListener('click', () => byId('sidebar').classList.add('open'));
    byId('close-sidebar').addEventListener('click', () => byId('sidebar').classList.remove('open'));
    byId('detail-close').addEventListener('click', () => byId('detail-dialog').close());
    byId('copy-summary').addEventListener('click', copyTeamSummary);
    for (const tab of document.querySelectorAll('.view-tab')) {
      tab.addEventListener('click', () => {
        state.currentView = tab.dataset.view;
        document.querySelectorAll('.view-tab').forEach((item) => item.classList.toggle('active', item === tab));
        document.querySelectorAll('.view').forEach((view) => view.classList.toggle('active', view.id === `${state.currentView}-view`));
        if (state.currentView === 'map' && state.map) setTimeout(() => state.map.invalidateSize(), 0);
      });
    }
    byId('login-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      const email = text(byId('login-email').value);
      const password = byId('login-password').value;
      const errorNode = byId('login-error');
      errorNode.textContent = '';
      const submit = event.submitter;
      submit.disabled = true;
      submit.textContent = 'Connexion…';
      try {
        const { data, error } = await state.client.auth.signInWithPassword({ email, password });
        if (error) throw error;
        state.user = data.user;
        await bootstrapShared();
        byId('login-password').value = '';
      } catch {
        errorNode.textContent = 'Email ou mot de passe incorrect.';
      } finally {
        submit.disabled = false;
        submit.textContent = 'Se connecter';
      }
    });
    byId('signout-button').addEventListener('click', async () => {
      try {
        await state.client.auth.signOut();
      } finally {
        window.sessionStorage.clear();
        clearSharedState();
      }
    });
    document.addEventListener('visibilitychange', async () => {
      if (document.visibilityState !== 'visible' || !state.pendingPhoneVenueId || !state.user) return;
      const venueId = state.pendingPhoneVenueId;
      state.pendingPhoneVenueId = null;
      try {
        await loadSnapshot();
        const followup = followupOf(venueId);
        if (isOwnLease(followup)) {
          await callRpc('renew_claim', {
            p_operation_id: operationId(), p_campaign_id: state.campaign.id, p_venue_id: venueId
          });
        }
      } catch {
        startPolling();
      }
      openDetail(venueId);
    });
  }

  async function init() {
    bindEvents();
    try {
      await loadPublicCatalog();
      byId('filter-summary').textContent = `${state.features.length} salles chargées`;
      initMap();
      renderAll();
      await initSupabase();
    } catch (error) {
      console.error({ code: error?.message, release: CONFIG.appRelease });
      showBanner('Le catalogue public ne peut pas être chargé. Réessaie plus tard.', 'error');
      byId('venue-list').replaceChildren(element('p', { className: 'empty-state', text: 'Catalogue indisponible.' }));
    }
  }

  init();
})();
