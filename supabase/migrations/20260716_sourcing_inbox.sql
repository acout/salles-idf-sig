-- Private, collaborative sourcing inbox for the existing calling cockpit.
-- Additive migration: the 20260714 venue cockpit contract remains valid.

create table if not exists public.sourcing_candidates (
  candidate_id uuid primary key default gen_random_uuid(),
  schema_version integer not null default 1 check (schema_version = 1),
  external_key text unique,
  legacy_venue_id text unique,
  linked_venue_id text references public.venue_registry(venue_id),
  duplicate_of_candidate_id uuid references public.sourcing_candidates(candidate_id),
  name text not null check (length(btrim(name)) between 1 and 200),
  address text check (address is null or length(address) <= 500),
  city text check (city is null or length(city) <= 160),
  department text check (department is null or department in ('75', '92', '93', '94', '77', '78', '91', '95')),
  lat double precision check (lat is null or lat between -90 and 90),
  lon double precision check (lon is null or lon between -180 and 180),
  capacity_max integer check (capacity_max is null or capacity_max between 1 and 100000),
  capacity_text text check (capacity_text is null or length(capacity_text) <= 500),
  price_text text check (price_text is null or length(price_text) <= 500),
  website_url text check (website_url is null or (length(website_url) <= 2000 and website_url ~* '^https?://')),
  contact_text text check (contact_text is null or length(contact_text) <= 1000),
  source_url text check (source_url is null or (length(source_url) <= 2000 and source_url ~* '^https?://')),
  category text check (category is null or length(category) <= 300),
  source_batch_key text not null default 'manual'
    check (source_batch_key in ('manual', 'sourcing_idf', 'banlieue_sud')),
  rental_status text not null default 'unknown'
    check (rental_status in ('possible', 'unclear', 'unknown')),
  confidence smallint check (confidence is null or confidence between 0 and 100),
  fit_score smallint check (fit_score is null or fit_score between 0 and 100),
  price_score smallint check (price_score is null or price_score between 0 and 100),
  pros text check (pros is null or length(pros) <= 4000),
  cons text check (cons is null or length(cons) <= 4000),
  last_checked date,
  page_type text check (page_type is null or length(page_type) <= 200),
  review_status text not null default 'unreviewed'
    check (review_status in ('unreviewed', 'in_review', 'validated', 'rejected', 'duplicate')),
  cockpit_visible boolean not null default false,
  assignee_id uuid references auth.users(id),
  version bigint not null default 0 check (version >= 0),
  created_by uuid references auth.users(id),
  updated_by uuid references auth.users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (not cockpit_visible or linked_venue_id is not null),
  check (review_status <> 'duplicate' or duplicate_of_candidate_id is not null or linked_venue_id is not null),
  check (duplicate_of_candidate_id is null or duplicate_of_candidate_id <> candidate_id)
);

create index if not exists sourcing_candidates_visible_review_updated_idx
  on public.sourcing_candidates (cockpit_visible, review_status, updated_at desc, candidate_id);
create index if not exists sourcing_candidates_assignee_review_updated_idx
  on public.sourcing_candidates (assignee_id, review_status, updated_at desc, candidate_id);
create index if not exists sourcing_candidates_linked_venue_idx
  on public.sourcing_candidates (linked_venue_id)
  where linked_venue_id is not null;

create table if not exists public.source_observations (
  observation_id uuid primary key default gen_random_uuid(),
  candidate_id uuid not null references public.sourcing_candidates(candidate_id) on delete cascade,
  source_type text not null check (source_type in ('manual', 'file', 'web', 'call')),
  source_url text check (source_url is null or (length(source_url) <= 2000 and source_url ~* '^https?://')),
  canonical_url text check (canonical_url is null or (length(canonical_url) <= 2000 and canonical_url ~* '^https?://')),
  observed_at timestamptz not null default now(),
  title text check (title is null or length(title) <= 500),
  excerpt text check (excerpt is null or length(excerpt) <= 4000),
  external_key text unique,
  created_by uuid references auth.users(id),
  created_at timestamptz not null default now()
);

create index if not exists source_observations_candidate_created_idx
  on public.source_observations (candidate_id, created_at desc);

create table if not exists public.candidate_evidence (
  evidence_id uuid primary key default gen_random_uuid(),
  candidate_id uuid not null references public.sourcing_candidates(candidate_id) on delete cascade,
  observation_id uuid references public.source_observations(observation_id) on delete set null,
  field_name text not null check (field_name in (
    'name', 'address', 'city', 'department', 'lat', 'lon', 'capacity_max',
    'capacity_text', 'price_text', 'website_url', 'contact_text', 'source_url'
  )),
  value jsonb not null,
  confidence smallint not null default 50 check (confidence between 0 and 100),
  resolution_status text not null default 'proposed'
    check (resolution_status in ('proposed', 'accepted', 'rejected')),
  resolved_by uuid references auth.users(id),
  resolved_at timestamptz,
  external_key text unique,
  created_at timestamptz not null default now(),
  check ((resolution_status = 'proposed' and resolved_by is null and resolved_at is null)
    or (resolution_status in ('accepted', 'rejected') and resolved_at is not null
      and (resolved_by is not null or external_key is not null)))
);

create index if not exists candidate_evidence_candidate_created_idx
  on public.candidate_evidence (candidate_id, created_at desc);

create table if not exists public.sourcing_events (
  event_id bigint generated always as identity primary key,
  candidate_id uuid not null references public.sourcing_candidates(candidate_id) on delete cascade,
  event_type text not null check (event_type in (
    'imported', 'created', 'claimed', 'updated', 'in_review', 'validated', 'rejected',
    'duplicate', 'promoted', 'visibility_changed'
  )),
  payload jsonb not null default '{}'::jsonb,
  operation_id uuid,
  external_key text unique,
  created_by uuid references auth.users(id),
  created_at timestamptz not null default now()
);

create index if not exists sourcing_events_candidate_created_idx
  on public.sourcing_events (candidate_id, event_id desc);
create index if not exists sourcing_events_cursor_idx
  on public.sourcing_events (event_id);

alter table public.sourcing_candidates enable row level security;
alter table public.source_observations enable row level security;
alter table public.candidate_evidence enable row level security;
alter table public.sourcing_events enable row level security;

drop policy if exists active_members_read_sourcing_candidates on public.sourcing_candidates;
create policy active_members_read_sourcing_candidates on public.sourcing_candidates
for select to authenticated using (private.is_active_member());

drop policy if exists active_members_read_source_observations on public.source_observations;
create policy active_members_read_source_observations on public.source_observations
for select to authenticated using (private.is_active_member());

drop policy if exists active_members_read_candidate_evidence on public.candidate_evidence;
create policy active_members_read_candidate_evidence on public.candidate_evidence
for select to authenticated using (private.is_active_member());

drop policy if exists active_members_read_sourcing_events on public.sourcing_events;
create policy active_members_read_sourcing_events on public.sourcing_events
for select to authenticated using (private.is_active_member());

grant select on public.sourcing_candidates, public.source_observations,
  public.candidate_evidence, public.sourcing_events to authenticated;
revoke insert, update, delete on public.sourcing_candidates, public.source_observations,
  public.candidate_evidence, public.sourcing_events from anon, authenticated;
revoke select on public.sourcing_candidates, public.source_observations,
  public.candidate_evidence, public.sourcing_events from anon;

create or replace function private.sourcing_candidate_json(p_candidate_id uuid)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
  select to_jsonb(sc)
  from public.sourcing_candidates sc
  where sc.candidate_id = p_candidate_id;
$$;

create or replace function private.sourcing_patch_is_valid(p_patch jsonb)
returns boolean
language sql
immutable
set search_path = ''
as $$
  select jsonb_typeof(p_patch) = 'object'
    and not exists (
      select 1
      from jsonb_object_keys(p_patch) as key
      where key not in (
        'name', 'address', 'city', 'department', 'lat', 'lon', 'capacity_max',
        'capacity_text', 'price_text', 'website_url', 'contact_text', 'source_url', 'assignee_id'
      )
    )
    and not exists (
      select 1
      from jsonb_each(p_patch) as item(key, value)
      where key in ('name', 'address', 'city', 'department', 'capacity_text', 'price_text',
        'website_url', 'contact_text', 'source_url', 'assignee_id')
        and jsonb_typeof(value) not in ('string', 'null')
    )
    and not exists (
      select 1
      from jsonb_each(p_patch) as item(key, value)
      where key in ('lat', 'lon', 'capacity_max')
        and jsonb_typeof(value) not in ('number', 'null')
    );
$$;

create or replace function private.add_manual_evidence(
  p_candidate_id uuid,
  p_observation_id uuid,
  p_values jsonb,
  p_resolution_status text default 'accepted'
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  field text;
begin
  foreach field in array array[
    'name', 'address', 'city', 'department', 'lat', 'lon', 'capacity_max',
    'capacity_text', 'price_text', 'website_url', 'contact_text', 'source_url'
  ]
  loop
    if p_values ? field and p_values->field <> 'null'::jsonb then
      insert into public.candidate_evidence (
        candidate_id, observation_id, field_name, value, confidence,
        resolution_status, resolved_by, resolved_at
      ) values (
        p_candidate_id, p_observation_id, field, p_values->field, 70,
        p_resolution_status,
        case when p_resolution_status = 'proposed' then null else auth.uid() end,
        case when p_resolution_status = 'proposed' then null else now() end
      );
    end if;
  end loop;
end;
$$;

revoke all on function private.sourcing_candidate_json(uuid) from public, anon, authenticated;
revoke all on function private.sourcing_patch_is_valid(jsonb) from public, anon, authenticated;
revoke all on function private.add_manual_evidence(uuid, uuid, jsonb, text) from public, anon, authenticated;

create or replace function public.create_sourcing_candidate(
  p_operation_id uuid,
  p_payload jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  saved jsonb;
  candidate_id uuid;
  observation_id uuid;
  response jsonb;
begin
  if not private.is_active_member() then
    return jsonb_build_object('ok', false, 'code', 'FORBIDDEN');
  end if;
  saved := private.lock_operation(p_operation_id);
  if saved is not null then return saved; end if;
  if not coalesce(private.sourcing_patch_is_valid(p_payload), false)
    or length(btrim(coalesce(p_payload->>'name', ''))) not between 1 and 200 then
    return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'VALIDATION_FAILED'));
  end if;
  if p_payload ? 'department' and p_payload->>'department' not in ('75', '92', '93', '94', '77', '78', '91', '95') then
    return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'VALIDATION_FAILED'));
  end if;
  if (p_payload ? 'website_url' and p_payload->>'website_url' !~* '^https?://')
    or (p_payload ? 'source_url' and p_payload->>'source_url' !~* '^https?://') then
    return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'VALIDATION_FAILED'));
  end if;

  insert into public.sourcing_candidates (
    name, address, city, department, lat, lon, capacity_max, capacity_text,
    price_text, website_url, contact_text, source_url, created_by, updated_by
  ) values (
    btrim(p_payload->>'name'), nullif(btrim(p_payload->>'address'), ''),
    nullif(btrim(p_payload->>'city'), ''), nullif(p_payload->>'department', ''),
    nullif(p_payload->>'lat', '')::double precision, nullif(p_payload->>'lon', '')::double precision,
    nullif(p_payload->>'capacity_max', '')::integer, nullif(btrim(p_payload->>'capacity_text'), ''),
    nullif(btrim(p_payload->>'price_text'), ''), nullif(btrim(p_payload->>'website_url'), ''),
    nullif(btrim(p_payload->>'contact_text'), ''), nullif(btrim(p_payload->>'source_url'), ''),
    auth.uid(), auth.uid()
  ) returning sourcing_candidates.candidate_id into candidate_id;

  insert into public.source_observations (
    candidate_id, source_type, source_url, canonical_url, title, excerpt, created_by
  ) values (
    candidate_id, 'manual', nullif(btrim(p_payload->>'source_url'), ''),
    nullif(btrim(p_payload->>'source_url'), ''), btrim(p_payload->>'name'),
    'Saisie manuelle depuis le Sourcing Inbox', auth.uid()
  ) returning source_observations.observation_id into observation_id;

  perform private.add_manual_evidence(candidate_id, observation_id, p_payload, 'accepted');
  insert into public.sourcing_events (candidate_id, event_type, payload, operation_id, created_by)
  values (candidate_id, 'created', p_payload, p_operation_id, auth.uid());
  response := jsonb_build_object('ok', true, 'code', 'CREATED',
    'candidate', private.sourcing_candidate_json(candidate_id));
  return private.save_operation(p_operation_id, response);
exception
  when invalid_text_representation or numeric_value_out_of_range or check_violation then
    return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'VALIDATION_FAILED'));
end;
$$;

create or replace function public.claim_sourcing_candidate(
  p_operation_id uuid,
  p_candidate_id uuid,
  p_expected_version bigint
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  saved jsonb;
  candidate public.sourcing_candidates%rowtype;
  response jsonb;
begin
  if not private.is_active_member() then
    return jsonb_build_object('ok', false, 'code', 'FORBIDDEN');
  end if;
  saved := private.lock_operation(p_operation_id);
  if saved is not null then return saved; end if;
  select * into candidate from public.sourcing_candidates where candidate_id = p_candidate_id for update;
  if not found then return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'CANDIDATE_NOT_FOUND')); end if;
  if p_expected_version is null or candidate.version <> p_expected_version then
    return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'STALE_WRITE', 'candidate', to_jsonb(candidate)));
  end if;
  if candidate.review_status in ('rejected', 'duplicate') then
    return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'INVALID_TRANSITION'));
  end if;
  if candidate.assignee_id is not null and candidate.assignee_id <> auth.uid() then
    return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'CLAIM_CONFLICT', 'candidate', to_jsonb(candidate)));
  end if;
  update public.sourcing_candidates set
    assignee_id = auth.uid(), review_status = 'in_review', version = version + 1,
    updated_by = auth.uid(), updated_at = now()
  where candidate_id = p_candidate_id;
  insert into public.sourcing_events (candidate_id, event_type, payload, operation_id, created_by)
  values (p_candidate_id, 'claimed', '{}'::jsonb, p_operation_id, auth.uid());
  response := jsonb_build_object('ok', true, 'code', 'CLAIMED',
    'candidate', private.sourcing_candidate_json(p_candidate_id));
  return private.save_operation(p_operation_id, response);
end;
$$;

create or replace function public.update_sourcing_candidate(
  p_operation_id uuid,
  p_candidate_id uuid,
  p_expected_version bigint,
  p_patch jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  saved jsonb;
  candidate public.sourcing_candidates%rowtype;
  observation_id uuid;
  new_assignee uuid;
  response jsonb;
begin
  if not private.is_active_member() then
    return jsonb_build_object('ok', false, 'code', 'FORBIDDEN');
  end if;
  saved := private.lock_operation(p_operation_id);
  if saved is not null then return saved; end if;
  if not coalesce(private.sourcing_patch_is_valid(p_patch), false) or p_patch = '{}'::jsonb then
    return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'VALIDATION_FAILED'));
  end if;
  select * into candidate from public.sourcing_candidates where candidate_id = p_candidate_id for update;
  if not found then return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'CANDIDATE_NOT_FOUND')); end if;
  if p_expected_version is null or candidate.version <> p_expected_version then
    return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'STALE_WRITE', 'candidate', to_jsonb(candidate)));
  end if;
  if candidate.review_status in ('rejected', 'duplicate') then
    return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'INVALID_TRANSITION'));
  end if;
  if p_patch ? 'assignee_id' and p_patch->'assignee_id' <> 'null'::jsonb then
    new_assignee := (p_patch->>'assignee_id')::uuid;
    if not private.is_active_member(new_assignee) then
      return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'INVALID_ASSIGNEE'));
    end if;
  end if;
  if p_patch ? 'name' and length(btrim(coalesce(p_patch->>'name', ''))) not between 1 and 200 then
    return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'VALIDATION_FAILED'));
  end if;
  if p_patch ? 'department' and p_patch->'department' <> 'null'::jsonb
    and p_patch->>'department' not in ('75', '92', '93', '94', '77', '78', '91', '95') then
    return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'VALIDATION_FAILED'));
  end if;
  if (p_patch ? 'website_url' and p_patch->'website_url' <> 'null'::jsonb and p_patch->>'website_url' !~* '^https?://')
    or (p_patch ? 'source_url' and p_patch->'source_url' <> 'null'::jsonb and p_patch->>'source_url' !~* '^https?://') then
    return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'VALIDATION_FAILED'));
  end if;

  update public.sourcing_candidates set
    name = case when p_patch ? 'name' then btrim(p_patch->>'name') else name end,
    address = case when p_patch ? 'address' then nullif(btrim(p_patch->>'address'), '') else address end,
    city = case when p_patch ? 'city' then nullif(btrim(p_patch->>'city'), '') else city end,
    department = case when p_patch ? 'department' then nullif(p_patch->>'department', '') else department end,
    lat = case when p_patch ? 'lat' then nullif(p_patch->>'lat', '')::double precision else lat end,
    lon = case when p_patch ? 'lon' then nullif(p_patch->>'lon', '')::double precision else lon end,
    capacity_max = case when p_patch ? 'capacity_max' then nullif(p_patch->>'capacity_max', '')::integer else capacity_max end,
    capacity_text = case when p_patch ? 'capacity_text' then nullif(btrim(p_patch->>'capacity_text'), '') else capacity_text end,
    price_text = case when p_patch ? 'price_text' then nullif(btrim(p_patch->>'price_text'), '') else price_text end,
    website_url = case when p_patch ? 'website_url' then nullif(btrim(p_patch->>'website_url'), '') else website_url end,
    contact_text = case when p_patch ? 'contact_text' then nullif(btrim(p_patch->>'contact_text'), '') else contact_text end,
    source_url = case when p_patch ? 'source_url' then nullif(btrim(p_patch->>'source_url'), '') else source_url end,
    assignee_id = case when p_patch ? 'assignee_id' then new_assignee else assignee_id end,
    review_status = case when review_status = 'validated' then 'in_review' else review_status end,
    version = version + 1, updated_by = auth.uid(), updated_at = now()
  where candidate_id = p_candidate_id;

  insert into public.source_observations (candidate_id, source_type, source_url, canonical_url, title, excerpt, created_by)
  values (p_candidate_id, 'manual', nullif(btrim(p_patch->>'source_url'), ''),
    nullif(btrim(p_patch->>'source_url'), ''), 'Modification manuelle',
    'Modification depuis le Sourcing Inbox', auth.uid())
  returning source_observations.observation_id into observation_id;
  perform private.add_manual_evidence(p_candidate_id, observation_id, p_patch, 'accepted');
  insert into public.sourcing_events (candidate_id, event_type, payload, operation_id, created_by)
  values (p_candidate_id, 'updated', p_patch, p_operation_id, auth.uid());
  response := jsonb_build_object('ok', true, 'code', 'UPDATED',
    'candidate', private.sourcing_candidate_json(p_candidate_id));
  return private.save_operation(p_operation_id, response);
exception
  when invalid_text_representation or numeric_value_out_of_range or check_violation then
    return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'VALIDATION_FAILED'));
end;
$$;

create or replace function public.set_sourcing_review_status(
  p_operation_id uuid,
  p_candidate_id uuid,
  p_expected_version bigint,
  p_status text,
  p_details jsonb default '{}'::jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  saved jsonb;
  candidate public.sourcing_candidates%rowtype;
  duplicate_candidate uuid;
  duplicate_venue text;
  reason text;
  response jsonb;
begin
  if not private.is_active_member() then
    return jsonb_build_object('ok', false, 'code', 'FORBIDDEN');
  end if;
  saved := private.lock_operation(p_operation_id);
  if saved is not null then return saved; end if;
  if p_status is null or p_status not in ('in_review', 'validated', 'rejected', 'duplicate')
    or jsonb_typeof(coalesce(p_details, '{}'::jsonb)) <> 'object' then
    return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'INVALID_TRANSITION'));
  end if;
  select * into candidate from public.sourcing_candidates where candidate_id = p_candidate_id for update;
  if not found then return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'CANDIDATE_NOT_FOUND')); end if;
  if p_expected_version is null or candidate.version <> p_expected_version then
    return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'STALE_WRITE', 'candidate', to_jsonb(candidate)));
  end if;
  if candidate.review_status in ('rejected', 'duplicate') then
    return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'INVALID_TRANSITION'));
  end if;
  if p_status = 'validated' and (
    length(btrim(candidate.name)) = 0
    or candidate.department is null
    or (candidate.city is null and candidate.address is null)
    or (candidate.contact_text is null and candidate.website_url is null and candidate.source_url is null)
  ) then
    return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'VALIDATION_FAILED'));
  end if;
  reason := nullif(btrim(p_details->>'reason'), '');
  if p_status = 'rejected' and (reason is null or length(reason) > 500) then
    return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'VALIDATION_FAILED'));
  end if;
  if p_status = 'duplicate' then
    begin duplicate_candidate := nullif(p_details->>'target_candidate_id', '')::uuid;
    exception when invalid_text_representation then
      return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'VALIDATION_FAILED'));
    end;
    duplicate_venue := nullif(btrim(p_details->>'target_venue_id'), '');
    if duplicate_candidate is null and duplicate_venue is null then
      return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'VALIDATION_FAILED'));
    end if;
    if duplicate_candidate is not null and not exists (
      select 1 from public.sourcing_candidates where candidate_id = duplicate_candidate and candidate_id <> p_candidate_id
    ) then
      return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'VALIDATION_FAILED'));
    end if;
    if duplicate_venue is not null and not exists (
      select 1 from public.venue_registry where venue_id = duplicate_venue
    ) then
      return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'VALIDATION_FAILED'));
    end if;
  end if;

  update public.sourcing_candidates set
    review_status = p_status,
    assignee_id = coalesce(assignee_id, auth.uid()),
    duplicate_of_candidate_id = case when p_status = 'duplicate' then duplicate_candidate else null end,
    linked_venue_id = case when p_status = 'duplicate' and duplicate_venue is not null then duplicate_venue else linked_venue_id end,
    cockpit_visible = case when p_status in ('rejected', 'duplicate') then false else cockpit_visible end,
    version = version + 1, updated_by = auth.uid(), updated_at = now()
  where candidate_id = p_candidate_id;
  insert into public.sourcing_events (candidate_id, event_type, payload, operation_id, created_by)
  values (p_candidate_id, p_status, coalesce(p_details, '{}'::jsonb), p_operation_id, auth.uid());
  response := jsonb_build_object('ok', true, 'code', upper(p_status),
    'candidate', private.sourcing_candidate_json(p_candidate_id));
  return private.save_operation(p_operation_id, response);
end;
$$;

-- Atomic visibility transition:
-- candidate(validated) -> venue_registry -> active campaign -> cockpit_visible.
-- Every visible venue has a campaign row; historical campaign rows may remain hidden.
create or replace function public.promote_sourcing_candidate(
  p_operation_id uuid,
  p_candidate_id uuid,
  p_expected_version bigint
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  saved jsonb;
  candidate public.sourcing_candidates%rowtype;
  active_campaign_id uuid;
  promoted_venue_id text;
  fingerprint text;
  response jsonb;
begin
  if not private.is_active_member() then
    return jsonb_build_object('ok', false, 'code', 'FORBIDDEN');
  end if;
  saved := private.lock_operation(p_operation_id);
  if saved is not null then return saved; end if;
  select * into candidate from public.sourcing_candidates where candidate_id = p_candidate_id for update;
  if not found then return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'CANDIDATE_NOT_FOUND')); end if;
  if p_expected_version is null or candidate.version <> p_expected_version then
    return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'STALE_WRITE', 'candidate', to_jsonb(candidate)));
  end if;
  if candidate.review_status <> 'validated' then
    return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'INVALID_TRANSITION'));
  end if;
  select ws.active_campaign_id into active_campaign_id
  from public.workspace_state ws where ws.singleton for update;
  if active_campaign_id is null or not exists (
    select 1 from public.campaigns where id = active_campaign_id and active
  ) then
    return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'CAMPAIGN_NOT_ACTIVE'));
  end if;
  promoted_venue_id := coalesce(candidate.linked_venue_id, 'venue_' || replace(gen_random_uuid()::text, '-', ''));
  fingerprint := encode(extensions.digest(concat_ws('|', candidate.candidate_id::text, candidate.name,
    candidate.address, candidate.city, candidate.department, candidate.source_url), 'sha256'), 'hex');
  insert into public.venue_registry (venue_id, source_fingerprint, active, updated_at)
  values (promoted_venue_id, fingerprint, true, now())
  on conflict (venue_id) do update set active = true, updated_at = now();
  insert into public.campaign_venues (campaign_id, venue_id, updated_by)
  values (active_campaign_id, promoted_venue_id, auth.uid())
  on conflict (campaign_id, venue_id) do nothing;
  update public.sourcing_candidates set
    linked_venue_id = promoted_venue_id, cockpit_visible = true, version = version + 1,
    updated_by = auth.uid(), updated_at = now()
  where candidate_id = p_candidate_id;
  insert into public.sourcing_events (candidate_id, event_type, payload, operation_id, created_by)
  values (p_candidate_id, 'promoted', jsonb_build_object('venue_id', promoted_venue_id, 'campaign_id', active_campaign_id),
    p_operation_id, auth.uid());
  response := jsonb_build_object('ok', true, 'code', 'PROMOTED',
    'candidate', private.sourcing_candidate_json(p_candidate_id),
    'campaignVenue', private.campaign_venue_json(active_campaign_id, promoted_venue_id));
  return private.save_operation(p_operation_id, response);
exception
  when others then
    return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'PROMOTION_FAILED'));
end;
$$;

revoke all on function public.create_sourcing_candidate(uuid, jsonb) from public, anon;
revoke all on function public.claim_sourcing_candidate(uuid, uuid, bigint) from public, anon;
revoke all on function public.update_sourcing_candidate(uuid, uuid, bigint, jsonb) from public, anon;
revoke all on function public.set_sourcing_review_status(uuid, uuid, bigint, text, jsonb) from public, anon;
revoke all on function public.promote_sourcing_candidate(uuid, uuid, bigint) from public, anon;

grant execute on function public.create_sourcing_candidate(uuid, jsonb) to authenticated;
grant execute on function public.claim_sourcing_candidate(uuid, uuid, bigint) to authenticated;
grant execute on function public.update_sourcing_candidate(uuid, uuid, bigint, jsonb) to authenticated;
grant execute on function public.set_sourcing_review_status(uuid, uuid, bigint, text, jsonb) to authenticated;
grant execute on function public.promote_sourcing_candidate(uuid, uuid, bigint) to authenticated;

alter table public.sourcing_candidates replica identity full;
alter table public.sourcing_events replica identity full;
do $$
begin
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'sourcing_candidates'
  ) then
    alter publication supabase_realtime add table public.sourcing_candidates;
  end if;
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'sourcing_events'
  ) then
    alter publication supabase_realtime add table public.sourcing_events;
  end if;
end;
$$;

update public.workspace_state
set max_client_contract_version = greatest(max_client_contract_version, 2), updated_at = now()
where singleton;
