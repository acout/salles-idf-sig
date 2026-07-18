begin;

create extension if not exists pgtap with schema extensions;
select plan(47);

insert into auth.users (
  instance_id, id, aud, role, email, encrypted_password,
  raw_app_meta_data, raw_user_meta_data, created_at, updated_at
) values
  ('00000000-0000-0000-0000-000000000000', '11111111-1111-1111-1111-111111111111',
    'authenticated', 'authenticated', 'member@example.test', '', '{}'::jsonb, '{}'::jsonb, now(), now()),
  ('00000000-0000-0000-0000-000000000000', '22222222-2222-2222-2222-222222222222',
    'authenticated', 'authenticated', 'other@example.test', '', '{}'::jsonb, '{}'::jsonb, now(), now()),
  ('00000000-0000-0000-0000-000000000000', '33333333-3333-3333-3333-333333333333',
    'authenticated', 'authenticated', 'inactive@example.test', '', '{}'::jsonb, '{}'::jsonb, now(), now()),
  ('00000000-0000-0000-0000-000000000000', '44444444-4444-4444-4444-444444444444',
    'authenticated', 'authenticated', 'outsider@example.test', '', '{}'::jsonb, '{}'::jsonb, now(), now());

insert into public.workspace_members (user_id, display_name, active) values
  ('11111111-1111-1111-1111-111111111111', 'Membre', true),
  ('22222222-2222-2222-2222-222222222222', 'Autre membre', true),
  ('33333333-3333-3333-3333-333333333333', 'Membre désactivé', false);

insert into public.campaigns (
  id, name, dataset_release_id, dataset_manifest_checksum, private_manifest, created_by
) values (
  'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'Campagne test', 'test-release', repeat('a', 64),
  jsonb_build_object('release_id', 'test-release', 'dataset_checksum', repeat('a', 64)),
  '11111111-1111-1111-1111-111111111111'
);

insert into public.workspace_state (
  singleton, owner_user_id, active_campaign_id, min_client_contract_version, max_client_contract_version
) values (
  true, '11111111-1111-1111-1111-111111111111',
  'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 1, 2
);

select has_table('public', 'sourcing_candidates', 'sourcing_candidates existe');
select has_table('public', 'source_observations', 'source_observations existe');
select has_table('public', 'candidate_evidence', 'candidate_evidence existe');
select has_table('public', 'sourcing_events', 'sourcing_events existe');
select has_column('public', 'sourcing_candidates', 'legacy_venue_id', 'l’identifiant legacy immuable existe');

select ok(not has_table_privilege('anon', 'public.sourcing_candidates', 'SELECT'),
  'un visiteur anonyme ne peut pas lire les candidates');
select ok(not has_table_privilege('authenticated', 'public.sourcing_candidates', 'INSERT'),
  'un membre ne peut pas insérer directement');
select ok(not has_table_privilege('authenticated', 'public.sourcing_candidates', 'UPDATE'),
  'un membre ne peut pas modifier directement');
select ok(has_table_privilege('authenticated', 'public.sourcing_candidates', 'SELECT'),
  'le rôle authentifié peut lire sous RLS');

set local role authenticated;
select set_config('request.jwt.claim.sub', '44444444-4444-4444-4444-444444444444', true);
select results_eq(
  $$select count(*) from public.sourcing_candidates$$,
  array[0::bigint],
  'un utilisateur non membre ne voit aucune candidate'
);
reset role;

select set_config('request.jwt.claim.sub', '11111111-1111-1111-1111-111111111111', true);
select is(
  public.create_sourcing_candidate(
    '10000000-0000-0000-0000-000000000000',
    jsonb_build_object('name', 'CapacitÃ© invalide', 'capacity_max', 0)
  )->>'code',
  'VALIDATION_FAILED',
  'une capacitÃ© nulle est refusÃ©e plutÃ´t que traitÃ©e comme connue'
);
select is((select count(*) from public.sourcing_candidates), 0::bigint,
  'une candidate invalide ne laisse aucune ligne partielle');

create temp table test_created as
select public.create_sourcing_candidate(
  '10000000-0000-0000-0000-000000000001',
  jsonb_build_object(
    'name', 'Salle test', 'city', 'Paris', 'department', '75',
    'address', '1 rue de Test', 'source_url', 'https://example.test/salle',
    'contact_text', '01 02 03 04 05', 'lat', 48.85, 'lon', 2.35,
    'capacity_max', 12
  )
) as response;

select is((select response->>'code' from test_created), 'CREATED', 'une candidate valide est créée');
select is((select count(*) from public.sourcing_candidates), 1::bigint, 'une seule candidate existe');
select is((select count(*) from public.source_observations), 1::bigint, 'la création ajoute une observation');
select cmp_ok((select count(*) from public.candidate_evidence), '>=', 6::bigint, 'la création ajoute des preuves');

set local role authenticated;
select results_eq(
  $$select count(*) from public.sourcing_candidates$$,
  array[1::bigint],
  'un membre actif peut lire les candidates'
);
reset role;

create temp table test_replay as
select public.create_sourcing_candidate(
  '10000000-0000-0000-0000-000000000001',
  jsonb_build_object('name', 'Ne doit pas être créée')
) as response;
select is((select response from test_replay), (select response from test_created), 'le replay renvoie la même réponse');
select is((select count(*) from public.sourcing_candidates), 1::bigint, 'le replay ne duplique pas la candidate');

update public.workspace_members set active = false where user_id = '11111111-1111-1111-1111-111111111111';
select is(
  public.create_sourcing_candidate(
    '10000000-0000-0000-0000-000000000001', jsonb_build_object('name', 'Replay interdit')
  )->>'code',
  'FORBIDDEN',
  'un membre désactivé ne peut pas relire une ancienne réponse par replay'
);
update public.workspace_members set active = true where user_id = '11111111-1111-1111-1111-111111111111';

create temp table test_ids as
select
  (response->'candidate'->>'candidate_id')::uuid as candidate_id,
  (response->'candidate'->>'version')::bigint as version
from test_created;

select is(
  public.claim_sourcing_candidate(
    '10000000-0000-0000-0000-000000000102', (select candidate_id from test_ids), null
  )->>'code',
  'STALE_WRITE',
  'une prise sans version attendue est refusée'
);

create temp table test_claim as
select public.claim_sourcing_candidate(
  '10000000-0000-0000-0000-000000000002',
  (select candidate_id from test_ids), 0
) as response;
select is((select response->>'code' from test_claim), 'CLAIMED', 'un membre peut prendre une candidate');

select is(
  public.update_sourcing_candidate(
    '10000000-0000-0000-0000-000000000103', (select candidate_id from test_ids), null,
    jsonb_build_object('price_text', 'Prix contourné')
  )->>'code',
  'STALE_WRITE',
  'une modification sans version attendue est refusée'
);

create temp table test_stale as
select public.update_sourcing_candidate(
  '10000000-0000-0000-0000-000000000003',
  (select candidate_id from test_ids), 0,
  jsonb_build_object('price_text', '100 EUR')
) as response;
select is((select response->>'code' from test_stale), 'STALE_WRITE', 'une version périmée est refusée');

create temp table test_update as
select public.update_sourcing_candidate(
  '10000000-0000-0000-0000-000000000004',
  (select candidate_id from test_ids), 1,
  jsonb_build_object('price_text', '100 EUR')
) as response;
select is((select response->>'code' from test_update), 'UPDATED', 'une modification à la bonne version réussit');

select is(
  public.set_sourcing_review_status(
    '10000000-0000-0000-0000-000000000106', (select candidate_id from test_ids), 2,
    null, '{}'::jsonb
  )->>'code',
  'INVALID_TRANSITION',
  'un statut nul renvoie une erreur métier stable'
);

select is(
  public.set_sourcing_review_status(
    '10000000-0000-0000-0000-000000000104', (select candidate_id from test_ids), null,
    'validated', '{}'::jsonb
  )->>'code',
  'STALE_WRITE',
  'une décision sans version attendue est refusée'
);

create temp table test_validate as
select public.set_sourcing_review_status(
  '10000000-0000-0000-0000-000000000005',
  (select candidate_id from test_ids), 2, 'validated', '{}'::jsonb
) as response;
select is((select response->>'code' from test_validate), 'VALIDATED', 'une candidate complète est validée');

select is(
  public.promote_sourcing_candidate(
    '10000000-0000-0000-0000-000000000105', (select candidate_id from test_ids), null
  )->>'code',
  'STALE_WRITE',
  'une promotion sans version attendue est refusée'
);

create temp table test_promote as
select public.promote_sourcing_candidate(
  '10000000-0000-0000-0000-000000000006',
  (select candidate_id from test_ids), 3
) as response;
select is((select response->>'code' from test_promote), 'PROMOTED', 'la promotion réussit');
select ok((select cockpit_visible from public.sourcing_candidates where candidate_id = (select candidate_id from test_ids)),
  'la candidate promue devient visible');
select ok(exists (
  select 1 from public.campaign_venues cv
  join public.sourcing_candidates sc on sc.linked_venue_id = cv.venue_id
  where sc.candidate_id = (select candidate_id from test_ids)
    and cv.campaign_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
), 'la promotion crée le rattachement de campagne');

select set_config('request.jwt.claim.sub', '44444444-4444-4444-4444-444444444444', true);
select is(
  public.create_sourcing_candidate(
    '10000000-0000-0000-0000-000000000007', jsonb_build_object('name', 'Interdit')
  )->>'code',
  'FORBIDDEN',
  'un utilisateur authentifié non membre ne peut pas muter'
);

select set_config('request.jwt.claim.sub', '33333333-3333-3333-3333-333333333333', true);
select is(
  public.create_sourcing_candidate(
    '10000000-0000-0000-0000-000000000008', jsonb_build_object('name', 'Interdit')
  )->>'code',
  'FORBIDDEN',
  'un membre désactivé ne peut pas muter'
);

select set_config('request.jwt.claim.sub', '11111111-1111-1111-1111-111111111111', true);
insert into public.venue_registry (venue_id, source_fingerprint) values ('venue_legacy', repeat('b', 64));
insert into public.campaign_venues (campaign_id, venue_id) values ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'venue_legacy');
insert into public.sourcing_candidates (
  candidate_id, external_key, linked_venue_id, name, city, department, source_url,
  review_status, cockpit_visible
) values (
  '55555555-5555-5555-5555-555555555555', 'legacy:test', 'venue_legacy',
  'Legacy', 'Arcueil', '94', 'https://example.test/legacy', 'unreviewed', true
);

create temp table test_reject as
select public.set_sourcing_review_status(
  '10000000-0000-0000-0000-000000000009',
  '55555555-5555-5555-5555-555555555555', 0, 'rejected',
  jsonb_build_object('reason', 'Pas une salle louable')
) as response;
select is((select response->>'code' from test_reject), 'REJECTED', 'un candidat peut être rejeté avec motif');
select ok(not (select cockpit_visible from public.sourcing_candidates where candidate_id = '55555555-5555-5555-5555-555555555555'),
  'un rejet masque la candidate');
select ok(exists (select 1 from public.campaign_venues where venue_id = 'venue_legacy'),
  'un rejet conserve la ligne de campagne historique');
select ok(exists (
  select 1 from public.sourcing_events
  where candidate_id = '55555555-5555-5555-5555-555555555555' and event_type = 'rejected'
), 'un rejet conserve un événement d’audit');

insert into public.sourcing_candidates (
  candidate_id, name, city, department, source_url, review_status
) values (
  '66666666-6666-6666-6666-666666666666', 'Concurrence', 'Paris', '75',
  'https://example.test/concurrence', 'in_review'
);
select set_config('request.jwt.claim.sub', '11111111-1111-1111-1111-111111111111', true);
create temp table test_concurrent_first as
select public.update_sourcing_candidate(
  '10000000-0000-0000-0000-000000000010',
  '66666666-6666-6666-6666-666666666666', 0,
  jsonb_build_object('price_text', 'Premier prix')
) as response;
select is((select response->>'code' from test_concurrent_first), 'UPDATED', 'le premier reviewer modifie la version courante');
select set_config('request.jwt.claim.sub', '22222222-2222-2222-2222-222222222222', true);
create temp table test_concurrent_second as
select public.update_sourcing_candidate(
  '10000000-0000-0000-0000-000000000011',
  '66666666-6666-6666-6666-666666666666', 0,
  jsonb_build_object('price_text', 'Écrasement interdit')
) as response;
select is((select response->>'code' from test_concurrent_second), 'STALE_WRITE', 'le second reviewer reçoit un conflit');
select is((select price_text from public.sourcing_candidates where candidate_id = '66666666-6666-6666-6666-666666666666'),
  'Premier prix', 'le conflit ne remplace pas la première modification');

select set_config('request.jwt.claim.sub', '11111111-1111-1111-1111-111111111111', true);
insert into public.sourcing_candidates (
  candidate_id, name, city, department, source_url, review_status
) values (
  '77777777-7777-7777-7777-777777777777', 'Promotion en échec', 'Paris', '75',
  'https://example.test/echec', 'validated'
);
update public.campaigns set active = false where id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
create temp table test_failed_promotion as
select public.promote_sourcing_candidate(
  '10000000-0000-0000-0000-000000000012',
  '77777777-7777-7777-7777-777777777777', 0
) as response;
select is((select response->>'code' from test_failed_promotion), 'CAMPAIGN_NOT_ACTIVE', 'une campagne inactive bloque la promotion');
select ok((select linked_venue_id is null and not cockpit_visible from public.sourcing_candidates
  where candidate_id = '77777777-7777-7777-7777-777777777777'), 'une promotion échouée ne modifie pas la candidate');
select is((select count(*) from public.venue_registry), 2::bigint, 'une promotion échouée ne crée aucun registre partiel');
update public.campaigns set active = true where id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';

insert into public.venue_registry (venue_id, source_fingerprint) values ('venue_duplicate', repeat('c', 64));
insert into public.campaign_venues (campaign_id, venue_id) values ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'venue_duplicate');
insert into public.sourcing_candidates (
  candidate_id, linked_venue_id, name, city, department, source_url, review_status, cockpit_visible
) values (
  '88888888-8888-8888-8888-888888888888', 'venue_duplicate', 'Doublon', 'Arcueil', '94',
  'https://example.test/doublon', 'in_review', true
);
create temp table test_duplicate as
select public.set_sourcing_review_status(
  '10000000-0000-0000-0000-000000000013',
  '88888888-8888-8888-8888-888888888888', 0, 'duplicate',
  jsonb_build_object('target_venue_id', 'venue_legacy')
) as response;
select is((select response->>'code' from test_duplicate), 'DUPLICATE', 'un doublon valide est accepté');
select ok(not (select cockpit_visible from public.sourcing_candidates where candidate_id = '88888888-8888-8888-8888-888888888888'),
  'un doublon disparaît du cockpit');
select ok(exists (select 1 from public.sourcing_events
  where candidate_id = '88888888-8888-8888-8888-888888888888' and event_type = 'duplicate'),
  'un doublon conserve son historique');

select * from finish();
rollback;
