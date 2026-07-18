(function attachSourcingInbox(root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.SourcingInbox = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function createSourcingInboxApi() {
  'use strict';

  const PAGE_SIZE = 100;
  const SNAPSHOT_PAGE_SIZE = 500;
  const POLL_MS = 10_000;
  const FULL_RESYNC_MS = 5 * 60_000;
  const CANDIDATE_COLUMNS = [
    'candidate_id', 'schema_version', 'external_key', 'legacy_venue_id', 'linked_venue_id', 'duplicate_of_candidate_id',
    'name', 'address', 'city', 'department', 'lat', 'lon', 'capacity_max', 'capacity_text',
    'price_text', 'website_url', 'contact_text', 'source_url', 'category', 'source_batch_key',
    'rental_status', 'confidence', 'fit_score', 'price_score', 'pros', 'cons', 'last_checked',
    'page_type', 'review_status', 'cockpit_visible', 'assignee_id', 'version', 'created_by',
    'updated_by', 'created_at', 'updated_at'
  ].join(',');
  const REVIEW_LABELS = Object.freeze({
    unreviewed: 'À revoir',
    in_review: 'En revue',
    validated: 'Validée',
    rejected: 'Rejetée',
    duplicate: 'Doublon'
  });
  const TERMINAL_STATUSES = new Set(['rejected', 'duplicate']);
  const IDF_BOUNDS = Object.freeze({ minLon: 1.4, maxLon: 3.7, minLat: 48, maxLat: 49.3 });

  const text = (value) => String(value ?? '').trim();
  const numberOrNull = (value) => {
    if (value === null || value === undefined || value === '') return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  };

  function catalogScope(row) {
    const lat = numberOrNull(row?.lat);
    const lon = numberOrNull(row?.lon);
    if (lat === null || lon === null || lon < IDF_BOUNDS.minLon || lon > IDF_BOUNDS.maxLon
      || lat < IDF_BOUNDS.minLat || lat > IDF_BOUNDS.maxLat) return 'geocode_review';
    return Number(row?.capacity_max || 0) > 20 ? 'capacity_over_20' : 'priority';
  }

  function batchLabel(key) {
    return {
      sourcing_idf: 'Batch sourcing IDF',
      banlieue_sud: 'Batch banlieue sud',
      manual: 'Sourcing partagé'
    }[key] || 'Sourcing partagé';
  }

  function candidateToFeature(row) {
    const lat = numberOrNull(row?.lat);
    const lon = numberOrNull(row?.lon);
    const batch = row?.source_batch_key || 'manual';
    return {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: lon === null || lat === null ? [0, 0] : [lon, lat] },
      properties: {
        id: text(row?.linked_venue_id),
        candidate_id: text(row?.candidate_id),
        name: text(row?.name),
        city: text(row?.city) || 'Localisation à confirmer',
        department: text(row?.department),
        address: text(row?.address) || text(row?.city),
        category: `${batchLabel(batch)} · ${text(row?.category) || 'salle à louer'}`,
        capacity_text: text(row?.capacity_text),
        capacity_max_detected: numberOrNull(row?.capacity_max) ?? '',
        price_text: text(row?.price_text),
        catalog_scope: catalogScope(row),
        candidate_origin: true,
        candidate_batch: batchLabel(batch),
        candidate_batch_key: batch,
        candidate_rental_status: text(row?.rental_status),
        sourcing_review_status: text(row?.review_status),
        sourcing_candidate_id: text(row?.candidate_id)
      }
    };
  }

  function candidateToPrivateDetails(row) {
    return {
      id: text(row?.linked_venue_id),
      website: text(row?.website_url),
      contact: text(row?.contact_text),
      source_url: text(row?.source_url),
      pros: text(row?.pros),
      cons: text(row?.cons),
      confidence: row?.confidence ?? '',
      fit_score: Number(row?.fit_score || 0),
      price_score: Number(row?.price_score || 0),
      last_checked: text(row?.last_checked),
      rental_status: text(row?.rental_status),
      candidate_status: text(row?.review_status),
      source_reliability: row?.confidence === null || row?.confidence === undefined ? '' : `${row.confidence}/100`,
      page_type: text(row?.page_type),
      sourcing_candidate_id: text(row?.candidate_id)
    };
  }

  function verifyLegacyParity(rows, expectedLegacyIds) {
    const expected = new Set(Array.from(expectedLegacyIds || []).map(text).filter(Boolean));
    if (!expected.size) return { ok: false, missing: [], duplicates: [], reason: 'NO_EXPECTED_IDS' };
    const seenLegacy = new Set();
    const seenVisible = new Set();
    const duplicates = new Set();
    for (const row of rows || []) {
      const legacyVenueId = text(row?.legacy_venue_id);
      if (legacyVenueId) seenLegacy.add(legacyVenueId);
      const visibleVenueId = row?.cockpit_visible ? text(row?.linked_venue_id) : '';
      if (!visibleVenueId) continue;
      if (seenVisible.has(visibleVenueId)) duplicates.add(visibleVenueId);
      seenVisible.add(visibleVenueId);
    }
    const missing = Array.from(expected).filter((venueId) => !seenLegacy.has(venueId));
    return {
      ok: missing.length === 0 && duplicates.size === 0,
      missing,
      duplicates: Array.from(duplicates),
      reason: missing.length ? 'MISSING_LEGACY_IDS' : duplicates.size ? 'DUPLICATE_VENUE_IDS' : 'OK'
    };
  }

  function prepareSnapshot(rows, expectedLegacyIds) {
    const parity = verifyLegacyParity(rows, expectedLegacyIds);
    const visibleRows = (rows || []).filter((row) => row.cockpit_visible && text(row.linked_venue_id));
    return { parity, visibleRows };
  }

  function missingFields(row) {
    const missing = [];
    if (!text(row?.city) && !text(row?.address)) missing.push('localisation');
    if (numberOrNull(row?.capacity_max) === null) missing.push('capacité');
    if (!text(row?.contact_text) && !text(row?.website_url) && !text(row?.source_url)) missing.push('contact');
    return missing;
  }

  function applyCandidateChange(rowsById, payload) {
    const next = payload?.new && Object.keys(payload.new).length ? payload.new : null;
    const previous = payload?.old && Object.keys(payload.old).length ? payload.old : null;
    const candidateId = text(next?.candidate_id || previous?.candidate_id);
    if (!candidateId) return { changed: false, visibleChanged: false, row: null };
    const existing = rowsById.get(candidateId) || previous;
    if (payload?.eventType === 'DELETE' || !next) rowsById.delete(candidateId);
    else rowsById.set(candidateId, next);
    return {
      changed: true,
      visibleChanged: Boolean(existing?.cockpit_visible) !== Boolean(next?.cockpit_visible)
        || text(existing?.linked_venue_id) !== text(next?.linked_venue_id)
        || Boolean(next?.cockpit_visible),
      row: next
    };
  }

  function safeSearch(value) {
    return text(value).replace(/[%_,().]/g, ' ').replace(/\s+/g, ' ').slice(0, 100);
  }

  function create(options = {}) {
    const callbacks = options.callbacks || {};
    const state = {
      client: options.client || null,
      userId: options.userId || null,
      members: options.members || new Map(),
      expectedLegacyIds: new Set(options.expectedLegacyIds || []),
      page: 0,
      pageCount: 1,
      pageRequestId: 0,
      total: 0,
      pageRows: [],
      rowsById: new Map(),
      visibleRows: new Map(),
      selectedId: null,
      channel: null,
      pollTimer: null,
      renderTimer: null,
      lastEventId: 0,
      lastFullSyncAt: 0,
      ready: false,
      destroyed: false,
      bound: false,
      abortController: null
    };

    const byId = (id) => typeof document === 'undefined' ? null : document.getElementById(id);
    const operationId = () => callbacks.operationId ? callbacks.operationId() : crypto.randomUUID();
    const memberName = (userId) => callbacks.memberName ? callbacks.memberName(userId) : (userId ? 'Membre' : 'Non attribuée');
    const toast = (message) => callbacks.toast?.(message);

    function listen(target, eventName, handler) {
      if (!target || !state.abortController) return;
      target.addEventListener(eventName, handler, { signal: state.abortController.signal });
    }

    function setHealth(mode, message) {
      const node = byId('sourcing-health');
      if (node) {
        node.textContent = message;
        node.className = `sourcing-health ${mode}`;
      }
      callbacks.onHealth?.(mode, message);
    }

    function businessError(code, payload) {
      const error = new Error(code || 'SOURCING_ERROR');
      error.code = code || 'SOURCING_ERROR';
      error.payload = payload;
      return error;
    }

    function friendlyError(error) {
      return {
        FORBIDDEN: 'Ce compte ne peut pas modifier le sourcing.',
        STALE_WRITE: 'Cette candidate a changé ailleurs. Sa fiche a été rechargée.',
        CLAIM_CONFLICT: 'Cette candidate est déjà prise par une autre personne.',
        INVALID_TRANSITION: 'Cette action n’est plus possible dans l’état actuel.',
        VALIDATION_FAILED: 'Il manque une information requise ou un champ est invalide.',
        CAMPAIGN_NOT_ACTIVE: 'La campagne active a changé. Recharge la page.',
        PROMOTION_FAILED: 'La promotion a échoué sans modifier partiellement la campagne.'
      }[error?.code] || 'Le sourcing ne peut pas être enregistré pour le moment.';
    }

    async function rpc(name, args) {
      const { data, error } = await state.client.rpc(name, args);
      if (error) throw error;
      if (!data?.ok) throw businessError(data?.code, data);
      if (state.destroyed) return data;
      if (data.candidate) applyRow(data.candidate, true);
      return data;
    }

    function emitVisibleSnapshot() {
      if (state.destroyed) return;
      const rows = Array.from(state.visibleRows.values())
        .filter((row) => row.cockpit_visible && text(row.linked_venue_id))
        .sort((a, b) => text(a.linked_venue_id).localeCompare(text(b.linked_venue_id)));
      callbacks.onVisibleSnapshot?.(rows, {
        features: rows.map(candidateToFeature),
        privateDetails: rows.map(candidateToPrivateDetails)
      });
    }

    function applyRow(row, emitVisible = false) {
      if (!row?.candidate_id) return;
      const previous = state.rowsById.get(row.candidate_id);
      state.rowsById.set(row.candidate_id, row);
      if (row.cockpit_visible && row.linked_venue_id) state.visibleRows.set(row.candidate_id, row);
      else state.visibleRows.delete(row.candidate_id);
      const pageIndex = state.pageRows.findIndex((item) => item.candidate_id === row.candidate_id);
      if (pageIndex >= 0) state.pageRows[pageIndex] = row;
      if (state.selectedId === row.candidate_id) populateCandidateForm(row);
      if (emitVisible || Boolean(previous?.cockpit_visible) !== Boolean(row.cockpit_visible)
        || (row.cockpit_visible && JSON.stringify(previous) !== JSON.stringify(row))) emitVisibleSnapshot();
    }

    async function loadVisibleSnapshot() {
      const rows = [];
      for (let from = 0; ; from += SNAPSHOT_PAGE_SIZE) {
        const { data, error } = await state.client
          .from('sourcing_candidates')
          .select(CANDIDATE_COLUMNS)
          .order('candidate_id', { ascending: true })
          .range(from, from + SNAPSHOT_PAGE_SIZE - 1);
        if (error) throw error;
        rows.push(...(data || []));
        if (!data || data.length < SNAPSHOT_PAGE_SIZE) break;
      }
      if (state.destroyed) return [];
      const { parity, visibleRows } = prepareSnapshot(rows, state.expectedLegacyIds);
      if (!parity.ok) throw businessError(`SOURCING_PARITY_${parity.reason}`, parity);
      state.visibleRows = new Map(visibleRows.map((row) => [row.candidate_id, row]));
      for (const row of rows) state.rowsById.set(row.candidate_id, row);
      state.lastFullSyncAt = Date.now();
      emitVisibleSnapshot();
      return rows;
    }

    function filters() {
      return {
        search: safeSearch(byId('sourcing-search')?.value),
        status: byId('sourcing-status-filter')?.value || 'all',
        department: byId('sourcing-department-filter')?.value || 'all',
        assignee: byId('sourcing-assignee-filter')?.value || 'all',
        missing: byId('sourcing-missing-filter')?.value || 'all'
      };
    }

    async function loadPage(page = state.page) {
      const requestId = ++state.pageRequestId;
      const selected = filters();
      const requestedPage = Math.max(0, page);
      let query = state.client
        .from('sourcing_candidates')
        .select(CANDIDATE_COLUMNS, { count: 'exact' });
      if (selected.status !== 'all') query = query.eq('review_status', selected.status);
      if (selected.department !== 'all') query = query.eq('department', selected.department);
      if (selected.assignee === 'me') query = query.eq('assignee_id', state.userId);
      else if (selected.assignee === 'unassigned') query = query.is('assignee_id', null);
      else if (selected.assignee !== 'all') query = query.eq('assignee_id', selected.assignee);
      if (selected.missing === 'capacity') query = query.is('capacity_max', null);
      else if (selected.missing === 'contact') {
        query = query.is('contact_text', null).is('website_url', null).is('source_url', null);
      } else if (selected.missing === 'location') {
        query = query.is('city', null).is('address', null);
      }
      if (selected.search) {
        query = query.or(`name.ilike.%${selected.search}%,city.ilike.%${selected.search}%,address.ilike.%${selected.search}%`);
      }
      const from = requestedPage * PAGE_SIZE;
      const { data, error, count } = await query
        .order('updated_at', { ascending: false })
        .order('candidate_id', { ascending: true })
        .range(from, from + PAGE_SIZE - 1);
      if (error) throw error;
      if (state.destroyed || requestId !== state.pageRequestId) return [];
      state.total = Number(count || 0);
      state.pageCount = Math.max(1, Math.ceil(state.total / PAGE_SIZE));
      state.page = Math.min(requestedPage, state.pageCount - 1);
      if (state.page !== requestedPage) return loadPage(state.page);
      state.pageRows = data || [];
      for (const row of state.pageRows) state.rowsById.set(row.candidate_id, row);
      render();
      return state.pageRows;
    }

    async function loadEventCursor() {
      const { data, error } = await state.client
        .from('sourcing_events')
        .select('event_id')
        .order('event_id', { ascending: false })
        .limit(1);
      if (error) throw error;
      if (state.destroyed) return;
      state.lastEventId = Number(data?.[0]?.event_id || 0);
    }

    async function pollChanges() {
      if (state.destroyed) return;
      for (let pass = 0; pass < 10; pass += 1) {
        const { data: events, error } = await state.client
          .from('sourcing_events')
          .select('event_id,candidate_id')
          .gt('event_id', state.lastEventId)
          .order('event_id', { ascending: true })
          .limit(100);
        if (error) throw error;
        if (!events?.length) break;
        state.lastEventId = Math.max(...events.map((event) => Number(event.event_id || 0)));
        const ids = Array.from(new Set(events.map((event) => event.candidate_id).filter(Boolean)));
        if (ids.length) {
          const { data: rows, error: rowsError } = await state.client
            .from('sourcing_candidates')
            .select(CANDIDATE_COLUMNS)
            .in('candidate_id', ids);
          if (rowsError) throw rowsError;
          if (state.destroyed) return;
          for (const row of rows || []) applyRow(row, false);
          emitVisibleSnapshot();
        }
        if (events.length < 100) break;
      }
      await loadPage(state.page);
      if (Date.now() - state.lastFullSyncAt > FULL_RESYNC_MS) await loadVisibleSnapshot();
      setHealth('polling', 'Sourcing synchronisé en mode secours · toutes les 10 s');
    }

    function stopPolling() {
      if (state.pollTimer) clearInterval(state.pollTimer);
      state.pollTimer = null;
    }

    function startPolling() {
      if (state.pollTimer || state.destroyed) return;
      setHealth('polling', 'Sourcing en mode secours · actualisation toutes les 10 s');
      state.pollTimer = setInterval(() => pollChanges().catch(() => {
        setHealth('error', 'Sourcing indisponible · les appels restent utilisables');
      }), POLL_MS);
    }

    function schedulePageRefresh() {
      clearTimeout(state.renderTimer);
      state.renderTimer = setTimeout(() => loadPage(state.page).catch(() => {
        setHealth('error', 'Liste sourcing temporairement indisponible');
      }), 150);
    }

    function handleRealtime(payload) {
      if (state.destroyed) return { changed: false, visibleChanged: false, row: null };
      const result = applyCandidateChange(state.rowsById, payload);
      if (!result.changed) return result;
      if (result.row?.cockpit_visible) state.visibleRows.set(result.row.candidate_id, result.row);
      else if (result.row?.candidate_id) state.visibleRows.delete(result.row.candidate_id);
      if (result.visibleChanged) emitVisibleSnapshot();
      schedulePageRefresh();
      return result;
    }

    async function setupRealtime() {
      if (state.channel) await state.client.removeChannel(state.channel);
      state.channel = state.client.channel('sourcing-inbox')
        .on('postgres_changes', { event: '*', schema: 'public', table: 'sourcing_candidates' }, handleRealtime)
        .subscribe((status) => {
          if (status === 'SUBSCRIBED') {
            pollChanges().then(() => {
              stopPolling();
              setHealth('realtime', 'Sourcing synchronisé avec l’équipe');
            }).catch(() => startPolling());
          } else if (['CHANNEL_ERROR', 'TIMED_OUT', 'CLOSED'].includes(status)) {
            startPolling();
          }
        });
    }

    function node(tag, options = {}, children = []) {
      const item = document.createElement(tag);
      if (options.className) item.className = options.className;
      if (options.text !== undefined) item.textContent = text(options.text);
      if (options.type) item.type = options.type;
      if (options.disabled) item.disabled = true;
      for (const child of children) if (child) item.append(child);
      return item;
    }

    function statusChip(row) {
      return node('span', { className: `mini-chip sourcing-${row.review_status}`, text: REVIEW_LABELS[row.review_status] || row.review_status });
    }

    function render() {
      if (typeof document === 'undefined') return;
      const list = byId('sourcing-list');
      if (!list) return;
      const fragment = document.createDocumentFragment();
      for (const row of state.pageRows) {
        const card = node('article', { className: 'sourcing-card' });
        const heading = node('div', { className: 'sourcing-card-heading' }, [
          node('div', {}, [
            node('h3', { text: row.name }),
            node('p', { text: [row.city, row.department, row.capacity_text].filter(Boolean).join(' · ') || 'Localisation à compléter' })
          ]),
          statusChip(row)
        ]);
        const chips = node('div', { className: 'card-tags' }, [
          row.cockpit_visible ? node('span', { className: 'mini-chip available', text: 'Dans les appels' }) : null,
          row.assignee_id ? node('span', { className: 'mini-chip neutral', text: memberName(row.assignee_id) }) : null,
          ...missingFields(row).map((field) => node('span', { className: 'mini-chip rental-unclear', text: `Manque ${field}` }))
        ]);
        const actions = node('div', { className: 'action-row' });
        if (!TERMINAL_STATUSES.has(row.review_status) && !row.assignee_id) {
          const claim = node('button', { className: 'secondary-button', type: 'button', text: 'Prendre' });
          claim.addEventListener('click', () => runButton(claim, async () => {
            await rpc('claim_sourcing_candidate', {
              p_operation_id: operationId(), p_candidate_id: row.candidate_id, p_expected_version: Number(row.version)
            });
            await loadPage(state.page);
          }, 'Candidate attribuée'));
          actions.append(claim);
        }
        const open = node('button', { className: 'primary-button', type: 'button', text: 'Ouvrir' });
        open.addEventListener('click', () => openCandidate(row.candidate_id).catch((error) => {
          console.error({ code: error?.code || error?.message, area: 'sourcing-history' });
          byId('sourcing-history')?.replaceChildren(node('p', {
            className: 'help', text: 'Historique temporairement indisponible. La fiche reste modifiable.'
          }));
          toast('L’historique ne peut pas être chargé pour le moment.');
        }));
        actions.append(open);
        card.append(heading, chips, actions);
        fragment.append(card);
      }
      if (!state.pageRows.length) fragment.append(node('p', { className: 'empty-state', text: 'Aucune candidate ne correspond à ces filtres.' }));
      list.replaceChildren(fragment);
      if (byId('sourcing-count')) byId('sourcing-count').textContent = String(state.total);
      if (byId('sourcing-page-label')) byId('sourcing-page-label').textContent = `Page ${state.page + 1} / ${state.pageCount} · ${state.total} candidate${state.total > 1 ? 's' : ''}`;
      if (byId('sourcing-prev')) byId('sourcing-prev').disabled = state.page <= 0;
      if (byId('sourcing-next')) byId('sourcing-next').disabled = state.page >= state.pageCount - 1;
    }

    async function runButton(button, action, successMessage) {
      button.disabled = true;
      const initial = button.textContent;
      button.textContent = 'Enregistrement…';
      try {
        await action();
        if (state.destroyed) return;
        if (successMessage) toast(successMessage);
      } catch (error) {
        if (state.destroyed) return;
        console.error({ code: error?.code || error?.message, area: 'sourcing' });
        toast(friendlyError(error));
        if (error?.payload?.candidate) applyRow(error.payload.candidate, true);
        await loadPage(state.page).catch(() => {});
      } finally {
        button.disabled = false;
        button.textContent = initial;
      }
    }

    function inputValue(id) {
      return text(byId(id)?.value);
    }

    function optionalNumber(id) {
      const value = inputValue(id);
      return value === '' ? null : Number(value);
    }

    function creationPayload() {
      return Object.fromEntries(Object.entries({
        name: inputValue('sourcing-create-name'),
        source_url: inputValue('sourcing-create-source'),
        city: inputValue('sourcing-create-city'),
        department: inputValue('sourcing-create-department'),
        contact_text: inputValue('sourcing-create-contact'),
        website_url: inputValue('sourcing-create-website'),
        capacity_max: optionalNumber('sourcing-create-capacity')
      }).filter(([, value]) => value !== '' && value !== null));
    }

    function editPatch() {
      return {
        name: inputValue('sourcing-edit-name'),
        source_url: inputValue('sourcing-edit-source') || null,
        city: inputValue('sourcing-edit-city') || null,
        department: inputValue('sourcing-edit-department') || null,
        address: inputValue('sourcing-edit-address') || null,
        contact_text: inputValue('sourcing-edit-contact') || null,
        website_url: inputValue('sourcing-edit-website') || null,
        capacity_max: optionalNumber('sourcing-edit-capacity'),
        capacity_text: inputValue('sourcing-edit-capacity-text') || null,
        price_text: inputValue('sourcing-edit-price') || null
      };
    }

    function setInput(id, value) {
      const input = byId(id);
      if (input) input.value = value ?? '';
    }

    function populateCandidateForm(row) {
      if (!row || typeof document === 'undefined') return;
      byId('sourcing-dialog-title').textContent = row.name;
      byId('sourcing-dialog-meta').textContent = `${REVIEW_LABELS[row.review_status] || row.review_status} · version ${row.version}${row.cockpit_visible ? ' · dans les appels' : ''}`;
      setInput('sourcing-edit-name', row.name);
      setInput('sourcing-edit-source', row.source_url);
      setInput('sourcing-edit-city', row.city);
      setInput('sourcing-edit-department', row.department);
      setInput('sourcing-edit-address', row.address);
      setInput('sourcing-edit-contact', row.contact_text);
      setInput('sourcing-edit-website', row.website_url);
      setInput('sourcing-edit-capacity', row.capacity_max);
      setInput('sourcing-edit-capacity-text', row.capacity_text);
      setInput('sourcing-edit-price', row.price_text);
      const terminal = TERMINAL_STATUSES.has(row.review_status);
      byId('sourcing-save').disabled = terminal;
      byId('sourcing-validate').disabled = terminal || row.review_status === 'validated';
      byId('sourcing-promote').disabled = row.review_status !== 'validated' || row.cockpit_visible;
      byId('sourcing-reject').disabled = terminal;
      byId('sourcing-duplicate').disabled = terminal;
    }

    async function openCandidate(candidateId) {
      state.selectedId = candidateId;
      let row = state.rowsById.get(candidateId);
      if (!row) {
        const { data, error } = await state.client.from('sourcing_candidates').select(CANDIDATE_COLUMNS).eq('candidate_id', candidateId).single();
        if (error) throw error;
        if (state.destroyed || state.selectedId !== candidateId) return;
        row = data;
        applyRow(row, false);
      }
      populateCandidateForm(row);
      const dialog = byId('sourcing-dialog');
      const history = byId('sourcing-history');
      history.replaceChildren(node('p', { className: 'help', text: 'Chargement de l’historique…' }));
      if (!dialog.open) dialog.showModal();
      const [observations, events] = await Promise.all([
        state.client.from('source_observations').select('observation_id,source_type,source_url,observed_at,title,excerpt').eq('candidate_id', candidateId).order('observed_at', { ascending: false }).limit(10),
        state.client.from('sourcing_events').select('event_id,event_type,payload,created_by,created_at').eq('candidate_id', candidateId).order('event_id', { ascending: false }).limit(20)
      ]);
      if (state.destroyed || state.selectedId !== candidateId) return;
      if (observations.error) throw observations.error;
      if (events.error) throw events.error;
      const fragment = document.createDocumentFragment();
      for (const observation of observations.data || []) {
        const link = observation.source_url ? node('a', { text: observation.title || observation.source_url }) : node('strong', { text: observation.title || 'Observation' });
        if (observation.source_url) {
          link.href = observation.source_url;
          link.target = '_blank';
          link.rel = 'noopener noreferrer';
        }
        fragment.append(node('div', { className: 'history-item' }, [
          node('time', { text: new Date(observation.observed_at).toLocaleString('fr-FR') }),
          link,
          node('div', { text: observation.excerpt || observation.source_type })
        ]));
      }
      for (const event of events.data || []) {
        const detail = text(event.payload?.reason)
          || (event.payload?.target_candidate_id ? `Doublon de la candidate ${text(event.payload.target_candidate_id)}` : '')
          || (event.payload?.target_venue_id ? `Doublon de la salle ${text(event.payload.target_venue_id)}` : '');
        fragment.append(node('div', { className: 'history-item' }, [
          node('time', { text: `${new Date(event.created_at).toLocaleString('fr-FR')} · ${memberName(event.created_by)}` }),
          node('strong', { text: event.event_type.replaceAll('_', ' ') }),
          detail ? node('div', { text: detail }) : null
        ]));
      }
      if (!fragment.childNodes.length) fragment.append(node('p', { className: 'help', text: 'Aucun historique.' }));
      history.replaceChildren(fragment);
    }

    function selectedRow() {
      return state.rowsById.get(state.selectedId);
    }

    function populateMemberFilter() {
      const select = byId('sourcing-assignee-filter');
      if (!select) return;
      for (const option of Array.from(select.querySelectorAll('option[data-member]'))) option.remove();
      for (const [userId, member] of state.members) {
        const option = document.createElement('option');
        option.value = userId;
        option.textContent = member?.display_name || memberName(userId);
        option.dataset.member = 'true';
        select.append(option);
      }
    }

    function bind() {
      if (state.bound || typeof document === 'undefined') return;
      state.bound = true;
      for (const id of ['sourcing-search', 'sourcing-status-filter', 'sourcing-department-filter', 'sourcing-assignee-filter', 'sourcing-missing-filter']) {
        const input = byId(id);
        const eventName = id === 'sourcing-search' ? 'input' : 'change';
        listen(input, eventName, () => {
          state.page = 0;
          schedulePageRefresh();
        });
      }
      listen(byId('sourcing-prev'), 'click', () => loadPage(state.page - 1));
      listen(byId('sourcing-next'), 'click', () => loadPage(state.page + 1));
      listen(byId('sourcing-dialog-close'), 'click', () => byId('sourcing-dialog').close());
      listen(byId('sourcing-create-form'), 'submit', async (event) => {
        event.preventDefault();
        const button = event.submitter;
        await runButton(button, async () => {
          const result = await rpc('create_sourcing_candidate', {
            p_operation_id: operationId(), p_payload: creationPayload()
          });
          event.currentTarget.reset();
          await loadPage(0);
          await openCandidate(result.candidate.candidate_id);
        }, 'Candidate ajoutée au sourcing');
      });
      listen(byId('sourcing-edit-form'), 'submit', async (event) => {
        event.preventDefault();
        const row = selectedRow();
        if (!row) return;
        await runButton(event.submitter, async () => {
          await rpc('update_sourcing_candidate', {
            p_operation_id: operationId(), p_candidate_id: row.candidate_id,
            p_expected_version: Number(row.version), p_patch: editPatch()
          });
          await loadPage(state.page);
        }, 'Candidate mise à jour');
      });
      listen(byId('sourcing-validate'), 'click', (event) => {
        const row = selectedRow();
        if (!row) return;
        runButton(event.currentTarget, async () => {
          await rpc('set_sourcing_review_status', {
            p_operation_id: operationId(), p_candidate_id: row.candidate_id,
            p_expected_version: Number(row.version), p_status: 'validated', p_details: {}
          });
          await loadPage(state.page);
        }, 'Candidate validée');
      });
      listen(byId('sourcing-promote'), 'click', (event) => {
        const row = selectedRow();
        if (!row) return;
        runButton(event.currentTarget, async () => {
          await rpc('promote_sourcing_candidate', {
            p_operation_id: operationId(), p_candidate_id: row.candidate_id,
            p_expected_version: Number(row.version)
          });
          await loadPage(state.page);
        }, 'Candidate ajoutée au cockpit d’appels');
      });
      listen(byId('sourcing-reject'), 'click', (event) => {
        const row = selectedRow();
        const reason = inputValue('sourcing-reject-reason');
        if (!row || !reason) {
          toast('Ajoute un motif de rejet.');
          return;
        }
        runButton(event.currentTarget, async () => {
          await rpc('set_sourcing_review_status', {
            p_operation_id: operationId(), p_candidate_id: row.candidate_id,
            p_expected_version: Number(row.version), p_status: 'rejected', p_details: { reason }
          });
          await loadPage(state.page);
        }, 'Candidate rejetée et masquée');
      });
      listen(byId('sourcing-duplicate'), 'click', (event) => {
        const row = selectedRow();
        const target = inputValue('sourcing-duplicate-target');
        if (!row || !target) {
          toast('Indique l’identifiant de la candidate ou de la salle cible.');
          return;
        }
        const isUuid = /^[0-9a-f]{8}-[0-9a-f-]{27}$/i.test(target);
        runButton(event.currentTarget, async () => {
          await rpc('set_sourcing_review_status', {
            p_operation_id: operationId(), p_candidate_id: row.candidate_id,
            p_expected_version: Number(row.version), p_status: 'duplicate',
            p_details: isUuid ? { target_candidate_id: target } : { target_venue_id: target }
          });
          await loadPage(state.page);
        }, 'Doublon conservé dans l’historique et masqué');
      });
    }

    async function init() {
      if (!state.client) throw businessError('SOURCING_CLIENT_MISSING');
      state.abortController?.abort();
      state.bound = false;
      state.destroyed = false;
      state.abortController = new AbortController();
      populateMemberFilter();
      bind();
      byId('sourcing-tab')?.classList.remove('hidden');
      setHealth('connecting', 'Chargement du sourcing partagé…');
      await loadEventCursor();
      await Promise.all([loadVisibleSnapshot(), loadPage(0)]);
      if (state.destroyed) throw businessError('SOURCING_DESTROYED');
      state.ready = true;
      startPolling();
      await setupRealtime();
      return { visibleCount: state.visibleRows.size, total: state.total };
    }

    async function destroy() {
      state.destroyed = true;
      state.ready = false;
      state.pageRequestId += 1;
      state.abortController?.abort();
      state.abortController = null;
      state.bound = false;
      stopPolling();
      clearTimeout(state.renderTimer);
      if (state.channel && state.client) await state.client.removeChannel(state.channel).catch(() => {});
      state.channel = null;
      state.rowsById.clear();
      state.visibleRows.clear();
      state.pageRows = [];
      state.selectedId = null;
      byId('sourcing-tab')?.classList.add('hidden');
      if (byId('sourcing-dialog')?.open) byId('sourcing-dialog').close();
    }

    return {
      init,
      destroy,
      loadPage,
      loadVisibleSnapshot,
      pollChanges,
      handleRealtime,
      render,
      get ready() { return state.ready; },
      get state() { return state; }
    };
  }

  return {
    PAGE_SIZE,
    CANDIDATE_COLUMNS,
    REVIEW_LABELS,
    candidateToFeature,
    candidateToPrivateDetails,
    verifyLegacyParity,
    prepareSnapshot,
    missingFields,
    applyCandidateChange,
    create
  };
});
