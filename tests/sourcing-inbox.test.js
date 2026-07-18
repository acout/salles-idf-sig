'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  PAGE_SIZE,
  candidateToFeature,
  candidateToPrivateDetails,
  verifyLegacyParity,
  prepareSnapshot,
  missingFields,
  applyCandidateChange
} = require('../public/js/sourcing-inbox.js');

function candidate(overrides = {}) {
  const linkedVenueId = overrides.linked_venue_id || 'venue_iflow_arcueil';
  return {
    candidate_id: '00000000-0000-4000-8000-000000000001',
    legacy_venue_id: linkedVenueId,
    linked_venue_id: linkedVenueId,
    name: 'iFlow Arcueil',
    city: 'Arcueil',
    department: '94',
    address: '10 rue Exemple',
    lat: 48.807,
    lon: 2.331,
    capacity_max: 18,
    capacity_text: 'Jusqu’à 18 personnes',
    price_text: 'Sur devis',
    category: 'Centre de réunion',
    source_batch_key: 'banlieue_sud',
    rental_status: 'possible',
    review_status: 'unreviewed',
    cockpit_visible: true,
    website_url: 'https://example.test',
    contact_text: '01 02 03 04 05',
    source_url: 'https://example.test/salle',
    pros: 'Proche du RER',
    cons: 'Prix à confirmer',
    confidence: 80,
    fit_score: 72,
    price_score: 60,
    last_checked: '2026-07-16',
    page_type: 'venue',
    ...overrides
  };
}

test('the Inbox keeps server pagination deliberately bounded', () => {
  assert.equal(PAGE_SIZE, 100);
});

test('a visible candidate becomes a canonical cockpit feature', () => {
  const feature = candidateToFeature(candidate());
  assert.equal(feature.properties.id, 'venue_iflow_arcueil');
  assert.equal(feature.properties.candidate_batch_key, 'banlieue_sud');
  assert.equal(feature.properties.catalog_scope, 'priority');
  assert.equal(feature.properties.capacity_max_detected, 18);
  assert.deepEqual(feature.geometry.coordinates, [2.331, 48.807]);
});

test('unknown coordinates and capacity stay explicit instead of becoming valid zeroes', () => {
  const feature = candidateToFeature(candidate({ lat: null, lon: null, capacity_max: null }));
  assert.deepEqual(feature.geometry.coordinates, [0, 0]);
  assert.equal(feature.properties.catalog_scope, 'geocode_review');
  assert.equal(feature.properties.capacity_max_detected, '');
});

test('private operational details retain contact and scoring information', () => {
  const details = candidateToPrivateDetails(candidate());
  assert.equal(details.id, 'venue_iflow_arcueil');
  assert.equal(details.contact, '01 02 03 04 05');
  assert.equal(details.fit_score, 72);
  assert.equal(details.source_reliability, '80/100');
});

test('legacy parity accepts extra new candidates but rejects any missing legacy venue', () => {
  const expected = ['legacy-a', 'legacy-b'];
  const complete = verifyLegacyParity([
    candidate({ candidate_id: 'a', linked_venue_id: 'legacy-a' }),
    candidate({ candidate_id: 'b', linked_venue_id: 'legacy-b' }),
    candidate({ candidate_id: 'c', linked_venue_id: 'new-manual' })
  ], expected);
  assert.equal(complete.ok, true);
  assert.deepEqual(complete.missing, []);

  const incomplete = verifyLegacyParity([
    candidate({ candidate_id: 'a', linked_venue_id: 'legacy-a' })
  ], expected);
  assert.equal(incomplete.ok, false);
  assert.deepEqual(incomplete.missing, ['legacy-b']);
});

test('legacy parity rejects two visible candidates linked to the same venue', () => {
  const result = verifyLegacyParity([
    candidate({ candidate_id: 'a', linked_venue_id: 'legacy-a' }),
    candidate({ candidate_id: 'b', linked_venue_id: 'legacy-a' })
  ], ['legacy-a']);
  assert.equal(result.ok, false);
  assert.deepEqual(result.duplicates, ['legacy-a']);
});

test('legacy parity keeps rejected candidates registered without rendering them', () => {
  const hidden = candidate({
    candidate_id: 'hidden-a',
    linked_venue_id: 'legacy-a',
    review_status: 'rejected',
    cockpit_visible: false
  });
  const visible = candidate({ candidate_id: 'visible-b', linked_venue_id: 'legacy-b' });
  const snapshot = prepareSnapshot([hidden, visible], ['legacy-a', 'legacy-b']);
  assert.equal(snapshot.parity.ok, true);
  assert.deepEqual(snapshot.visibleRows.map((row) => row.linked_venue_id), ['legacy-b']);
});

test('legacy parity separates immutable import identity from duplicate linkage', () => {
  const original = candidate({
    candidate_id: 'original',
    legacy_venue_id: 'legacy-a',
    linked_venue_id: 'legacy-a'
  });
  const duplicate = candidate({
    candidate_id: 'duplicate',
    legacy_venue_id: 'legacy-b',
    linked_venue_id: 'legacy-a',
    review_status: 'duplicate',
    cockpit_visible: false
  });
  const snapshot = prepareSnapshot([original, duplicate], ['legacy-a', 'legacy-b']);
  assert.equal(snapshot.parity.ok, true);
  assert.deepEqual(snapshot.visibleRows.map((row) => row.candidate_id), ['original']);
});

test('missing-field hints match the qualification filters', () => {
  assert.deepEqual(missingFields(candidate({
    city: null,
    address: null,
    capacity_max: null,
    contact_text: null,
    website_url: null,
    source_url: null
  })), ['localisation', 'capacité', 'contact']);
});

test('realtime inserts, visibility changes, and deletes update the local index', () => {
  const rows = new Map();
  const visible = candidate();
  let result = applyCandidateChange(rows, { eventType: 'INSERT', new: visible, old: {} });
  assert.equal(result.changed, true);
  assert.equal(result.visibleChanged, true);
  assert.equal(rows.get(visible.candidate_id).name, 'iFlow Arcueil');

  const hidden = { ...visible, cockpit_visible: false, version: 2 };
  result = applyCandidateChange(rows, { eventType: 'UPDATE', new: hidden, old: visible });
  assert.equal(result.visibleChanged, true);
  assert.equal(rows.get(visible.candidate_id).cockpit_visible, false);

  result = applyCandidateChange(rows, { eventType: 'DELETE', new: {}, old: hidden });
  assert.equal(result.changed, true);
  assert.equal(rows.has(visible.candidate_id), false);
});

test('a large visible snapshot maps deterministically without dropping rows', () => {
  const rows = Array.from({ length: 5_000 }, (_, index) => candidate({
    candidate_id: `candidate-${index}`,
    linked_venue_id: `venue-${index}`
  }));
  const features = rows.map(candidateToFeature);
  assert.equal(features.length, 5_000);
  assert.equal(new Set(features.map((feature) => feature.properties.id)).size, 5_000);
});
