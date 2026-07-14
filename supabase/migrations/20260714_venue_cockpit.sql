-- Salles IDF shared calling cockpit.
-- Apply to a dedicated Supabase project, then bootstrap it with
-- scripts/admin_bootstrap_supabase.py. All client writes go through RPCs.

create extension if not exists pgcrypto;

create schema if not exists private;
revoke all on schema private from public, anon, authenticated;
grant usage on schema private to authenticated;

create table if not exists public.workspace_members (
  user_id uuid primary key references auth.users(id) on delete cascade,
  display_name text not null check (length(btrim(display_name)) between 1 and 100),
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.venue_registry (
  venue_id text primary key,
  source_fingerprint text not null check (source_fingerprint ~ '^[0-9a-f]{64}$'),
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.campaigns (
  id uuid primary key default gen_random_uuid(),
  name text not null check (length(btrim(name)) between 1 and 160),
  event_date date,
  dataset_release_id text not null,
  dataset_manifest_checksum text not null check (dataset_manifest_checksum ~ '^[0-9a-f]{64}$'),
  private_manifest jsonb not null,
  active boolean not null default true,
  created_by uuid not null references auth.users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (private_manifest->>'release_id' = dataset_release_id),
  check (private_manifest->>'dataset_checksum' = dataset_manifest_checksum)
);

create table if not exists public.workspace_state (
  singleton boolean primary key default true check (singleton),
  owner_user_id uuid not null references auth.users(id),
  active_campaign_id uuid not null references public.campaigns(id),
  min_client_contract_version integer not null default 1 check (min_client_contract_version > 0),
  max_client_contract_version integer not null default 1 check (max_client_contract_version >= min_client_contract_version),
  updated_at timestamptz not null default now()
);

create table if not exists public.campaign_venues (
  campaign_id uuid not null references public.campaigns(id) on delete cascade,
  venue_id text not null references public.venue_registry(venue_id),
  is_shortlisted boolean not null default false,
  assignee_id uuid references auth.users(id),
  status text not null default 'to_call' check (status in ('to_call', 'callback', 'available', 'needs_confirmation', 'unavailable')),
  availability_text text check (availability_text is null or length(availability_text) <= 500),
  confirmed_price_text text check (confirmed_price_text is null or length(confirmed_price_text) <= 500),
  next_action_at timestamptz,
  claimed_by uuid references auth.users(id),
  claim_expires_at timestamptz,
  version bigint not null default 0 check (version >= 0),
  updated_by uuid references auth.users(id),
  updated_at timestamptz not null default now(),
  primary key (campaign_id, venue_id),
  check ((claimed_by is null and claim_expires_at is null) or (claimed_by is not null and claim_expires_at is not null)),
  check (status <> 'callback' or next_action_at is not null)
);

create index if not exists campaign_venues_campaign_status_idx
  on public.campaign_venues (campaign_id, status, is_shortlisted);
create index if not exists campaign_venues_claim_idx
  on public.campaign_venues (campaign_id, claim_expires_at)
  where claimed_by is not null;

create table if not exists public.venue_activities (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references public.campaigns(id) on delete cascade,
  venue_id text not null references public.venue_registry(venue_id),
  activity_type text not null check (activity_type in ('claim', 'renew_claim', 'release_claim', 'takeover_claim', 'call_result', 'call_correction', 'field_update', 'note')),
  field_name text,
  old_value jsonb,
  new_value jsonb,
  note text check (note is null or length(note) <= 2000),
  created_by uuid not null references auth.users(id),
  created_at timestamptz not null default now()
);

create index if not exists venue_activities_campaign_created_idx
  on public.venue_activities (campaign_id, created_at desc);
create index if not exists venue_activities_venue_created_idx
  on public.venue_activities (campaign_id, venue_id, created_at desc);

create table if not exists public.operation_receipts (
  user_id uuid not null references auth.users(id) on delete cascade,
  operation_id uuid not null,
  response jsonb not null,
  created_at timestamptz not null default now(),
  primary key (user_id, operation_id)
);

alter table public.workspace_members enable row level security;
alter table public.venue_registry enable row level security;
alter table public.campaigns enable row level security;
alter table public.workspace_state enable row level security;
alter table public.campaign_venues enable row level security;
alter table public.venue_activities enable row level security;
alter table public.operation_receipts enable row level security;

create or replace function private.is_active_member(p_user_id uuid default auth.uid())
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.workspace_members wm
    where wm.user_id = p_user_id and wm.active
  );
$$;

revoke all on function private.is_active_member(uuid) from public, anon, authenticated;
grant execute on function private.is_active_member(uuid) to authenticated;

drop policy if exists members_read_workspace_members on public.workspace_members;
create policy members_read_workspace_members on public.workspace_members
for select to authenticated using (private.is_active_member());

drop policy if exists members_read_campaigns on public.campaigns;
create policy members_read_campaigns on public.campaigns
for select to authenticated using (private.is_active_member());

drop policy if exists members_read_workspace_state on public.workspace_state;
create policy members_read_workspace_state on public.workspace_state
for select to authenticated using (private.is_active_member());

drop policy if exists members_read_campaign_venues on public.campaign_venues;
create policy members_read_campaign_venues on public.campaign_venues
for select to authenticated using (private.is_active_member());

drop policy if exists members_read_venue_activities on public.venue_activities;
create policy members_read_venue_activities on public.venue_activities
for select to authenticated using (private.is_active_member());

grant select on public.workspace_members, public.campaigns, public.workspace_state,
  public.campaign_venues, public.venue_activities to authenticated;
revoke insert, update, delete on public.workspace_members, public.venue_registry,
  public.campaigns, public.workspace_state, public.campaign_venues,
  public.venue_activities, public.operation_receipts from anon, authenticated;

create or replace function private.lock_operation(p_operation_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  saved jsonb;
begin
  if p_operation_id is null or auth.uid() is null then
    return jsonb_build_object('ok', false, 'code', 'INVALID_OPERATION');
  end if;
  perform pg_advisory_xact_lock(hashtextextended(auth.uid()::text || ':' || p_operation_id::text, 0));
  select r.response into saved
  from public.operation_receipts r
  where r.user_id = auth.uid() and r.operation_id = p_operation_id;
  return saved;
end;
$$;

create or replace function private.save_operation(p_operation_id uuid, p_response jsonb)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.operation_receipts (user_id, operation_id, response)
  values (auth.uid(), p_operation_id, p_response)
  on conflict (user_id, operation_id) do update set response = excluded.response;
  return p_response;
end;
$$;

create or replace function private.lock_active_campaign(p_campaign_id uuid)
returns text
language plpgsql
security definer
set search_path = ''
as $$
declare
  active_id uuid;
begin
  if not private.is_active_member() then return 'FORBIDDEN'; end if;
  select ws.active_campaign_id into active_id
  from public.workspace_state ws
  where ws.singleton
  for update;
  if active_id is null then return 'WORKSPACE_NOT_CONFIGURED'; end if;
  if active_id <> p_campaign_id then return 'CAMPAIGN_NOT_ACTIVE'; end if;
  return null;
end;
$$;

create or replace function private.campaign_venue_json(p_campaign_id uuid, p_venue_id text)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
  select to_jsonb(cv)
  from public.campaign_venues cv
  where cv.campaign_id = p_campaign_id and cv.venue_id = p_venue_id;
$$;

revoke all on function private.lock_operation(uuid) from public, anon, authenticated;
revoke all on function private.save_operation(uuid, jsonb) from public, anon, authenticated;
revoke all on function private.lock_active_campaign(uuid) from public, anon, authenticated;
revoke all on function private.campaign_venue_json(uuid, text) from public, anon, authenticated;

create or replace function public.get_workspace_bootstrap(p_client_contract_version integer)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  ws public.workspace_state%rowtype;
  member_json jsonb;
  campaign_json jsonb;
  members_json jsonb;
begin
  if not private.is_active_member() then
    return jsonb_build_object('ok', false, 'code', 'FORBIDDEN');
  end if;
  select * into ws from public.workspace_state where singleton;
  if not found then return jsonb_build_object('ok', false, 'code', 'WORKSPACE_NOT_CONFIGURED'); end if;
  if p_client_contract_version < ws.min_client_contract_version or p_client_contract_version > ws.max_client_contract_version then
    return jsonb_build_object('ok', false, 'code', 'CLIENT_UPGRADE_REQUIRED');
  end if;
  select to_jsonb(wm) into member_json
  from public.workspace_members wm where wm.user_id = auth.uid() and wm.active;
  select to_jsonb(c) into campaign_json
  from public.campaigns c where c.id = ws.active_campaign_id and c.active;
  if campaign_json is null then return jsonb_build_object('ok', false, 'code', 'CAMPAIGN_NOT_ACTIVE'); end if;
  select coalesce(jsonb_agg(to_jsonb(wm) order by wm.display_name), '[]'::jsonb) into members_json
  from public.workspace_members wm where wm.active;
  return jsonb_build_object(
    'ok', true,
    'code', 'OK',
    'member', member_json,
    'campaign', campaign_json,
    'members', members_json,
    'serverTime', now()
  );
end;
$$;

create or replace function public.claim_venue(
  p_operation_id uuid,
  p_campaign_id uuid,
  p_venue_id text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  saved jsonb;
  problem text;
  cv public.campaign_venues%rowtype;
  response jsonb;
begin
  saved := private.lock_operation(p_operation_id); if saved is not null then return saved; end if;
  problem := private.lock_active_campaign(p_campaign_id);
  if problem is not null then return jsonb_build_object('ok', false, 'code', problem); end if;
  select * into cv from public.campaign_venues
  where campaign_id = p_campaign_id and venue_id = p_venue_id for update;
  if not found then return jsonb_build_object('ok', false, 'code', 'VENUE_NOT_FOUND'); end if;
  if cv.claimed_by is not null and cv.claim_expires_at > now() and cv.claimed_by <> auth.uid() then
    return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'CLAIM_CONFLICT'));
  end if;
  if cv.status not in ('to_call', 'callback', 'needs_confirmation') then
    return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'VENUE_NOT_CALLABLE'));
  end if;
  update public.campaign_venues set
    claimed_by = auth.uid(), claim_expires_at = now() + interval '7 minutes',
    assignee_id = coalesce(assignee_id, auth.uid()), version = version + 1,
    updated_by = auth.uid(), updated_at = now()
  where campaign_id = p_campaign_id and venue_id = p_venue_id;
  insert into public.venue_activities (campaign_id, venue_id, activity_type, created_by)
  values (p_campaign_id, p_venue_id, 'claim', auth.uid());
  response := jsonb_build_object('ok', true, 'code', 'CLAIMED', 'campaignVenue', private.campaign_venue_json(p_campaign_id, p_venue_id));
  return private.save_operation(p_operation_id, response);
end;
$$;

create or replace function public.renew_claim(p_operation_id uuid, p_campaign_id uuid, p_venue_id text)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare saved jsonb; problem text; cv public.campaign_venues%rowtype; response jsonb;
begin
  saved := private.lock_operation(p_operation_id); if saved is not null then return saved; end if;
  problem := private.lock_active_campaign(p_campaign_id); if problem is not null then return jsonb_build_object('ok', false, 'code', problem); end if;
  select * into cv from public.campaign_venues where campaign_id = p_campaign_id and venue_id = p_venue_id for update;
  if not found then return jsonb_build_object('ok', false, 'code', 'VENUE_NOT_FOUND'); end if;
  if cv.claimed_by is distinct from auth.uid() or cv.claim_expires_at < now() - interval '30 seconds' then
    return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'CLAIM_LOST'));
  end if;
  update public.campaign_venues set claim_expires_at = now() + interval '7 minutes', version = version + 1, updated_by = auth.uid(), updated_at = now()
  where campaign_id = p_campaign_id and venue_id = p_venue_id;
  insert into public.venue_activities (campaign_id, venue_id, activity_type, created_by) values (p_campaign_id, p_venue_id, 'renew_claim', auth.uid());
  response := jsonb_build_object('ok', true, 'code', 'RENEWED', 'campaignVenue', private.campaign_venue_json(p_campaign_id, p_venue_id));
  return private.save_operation(p_operation_id, response);
end;
$$;

create or replace function public.release_claim(p_operation_id uuid, p_campaign_id uuid, p_venue_id text)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare saved jsonb; problem text; cv public.campaign_venues%rowtype; response jsonb;
begin
  saved := private.lock_operation(p_operation_id); if saved is not null then return saved; end if;
  problem := private.lock_active_campaign(p_campaign_id); if problem is not null then return jsonb_build_object('ok', false, 'code', problem); end if;
  select * into cv from public.campaign_venues where campaign_id = p_campaign_id and venue_id = p_venue_id for update;
  if not found then return jsonb_build_object('ok', false, 'code', 'VENUE_NOT_FOUND'); end if;
  if cv.claimed_by is distinct from auth.uid() then return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'NOT_CLAIM_OWNER')); end if;
  update public.campaign_venues set claimed_by = null, claim_expires_at = null, version = version + 1, updated_by = auth.uid(), updated_at = now()
  where campaign_id = p_campaign_id and venue_id = p_venue_id;
  insert into public.venue_activities (campaign_id, venue_id, activity_type, created_by) values (p_campaign_id, p_venue_id, 'release_claim', auth.uid());
  response := jsonb_build_object('ok', true, 'code', 'RELEASED', 'campaignVenue', private.campaign_venue_json(p_campaign_id, p_venue_id));
  return private.save_operation(p_operation_id, response);
end;
$$;

create or replace function public.take_over_stale_claim(
  p_operation_id uuid,
  p_campaign_id uuid,
  p_venue_id text,
  p_observed_claimed_by uuid,
  p_observed_expiry timestamptz
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare saved jsonb; problem text; cv public.campaign_venues%rowtype; response jsonb;
begin
  saved := private.lock_operation(p_operation_id); if saved is not null then return saved; end if;
  problem := private.lock_active_campaign(p_campaign_id); if problem is not null then return jsonb_build_object('ok', false, 'code', problem); end if;
  select * into cv from public.campaign_venues where campaign_id = p_campaign_id and venue_id = p_venue_id for update;
  if not found then return jsonb_build_object('ok', false, 'code', 'VENUE_NOT_FOUND'); end if;
  if cv.claimed_by is distinct from p_observed_claimed_by or cv.claim_expires_at is distinct from p_observed_expiry or cv.claim_expires_at > now() then
    return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'CLAIM_CHANGED'));
  end if;
  update public.campaign_venues set claimed_by = auth.uid(), claim_expires_at = now() + interval '7 minutes',
    assignee_id = coalesce(assignee_id, auth.uid()), version = version + 1, updated_by = auth.uid(), updated_at = now()
  where campaign_id = p_campaign_id and venue_id = p_venue_id;
  insert into public.venue_activities (campaign_id, venue_id, activity_type, old_value, new_value, created_by)
  values (p_campaign_id, p_venue_id, 'takeover_claim', to_jsonb(p_observed_claimed_by), to_jsonb(auth.uid()), auth.uid());
  response := jsonb_build_object('ok', true, 'code', 'TAKEN_OVER', 'campaignVenue', private.campaign_venue_json(p_campaign_id, p_venue_id));
  return private.save_operation(p_operation_id, response);
end;
$$;

create or replace function private.save_call_result(
  p_operation_id uuid,
  p_campaign_id uuid,
  p_venue_id text,
  p_result_status text,
  p_availability_text text,
  p_confirmed_price_text text,
  p_next_action_at timestamptz,
  p_note text,
  p_is_correction boolean
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare saved jsonb; problem text; cv public.campaign_venues%rowtype; response jsonb;
begin
  saved := private.lock_operation(p_operation_id); if saved is not null then return saved; end if;
  problem := private.lock_active_campaign(p_campaign_id); if problem is not null then return jsonb_build_object('ok', false, 'code', problem); end if;
  if p_result_status not in ('available', 'unavailable', 'callback', 'needs_confirmation') then return jsonb_build_object('ok', false, 'code', 'INVALID_STATUS'); end if;
  if p_result_status = 'callback' and p_next_action_at is null then return jsonb_build_object('ok', false, 'code', 'CALLBACK_DATE_REQUIRED'); end if;
  if length(btrim(coalesce(p_note, ''))) = 0 or length(p_note) > 2000 then return jsonb_build_object('ok', false, 'code', 'NOTE_REQUIRED'); end if;
  select * into cv from public.campaign_venues where campaign_id = p_campaign_id and venue_id = p_venue_id for update;
  if not found then return jsonb_build_object('ok', false, 'code', 'VENUE_NOT_FOUND'); end if;
  if p_is_correction then
    if cv.status = 'to_call' then return jsonb_build_object('ok', false, 'code', 'NOTHING_TO_CORRECT'); end if;
    if cv.claimed_by is not null and cv.claim_expires_at > now() and cv.claimed_by <> auth.uid() then return jsonb_build_object('ok', false, 'code', 'CLAIM_CONFLICT'); end if;
  elsif cv.claimed_by is distinct from auth.uid() or cv.claim_expires_at <= now() then
    return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'CLAIM_LOST'));
  end if;
  update public.campaign_venues set
    status = p_result_status,
    availability_text = nullif(btrim(p_availability_text), ''),
    confirmed_price_text = nullif(btrim(p_confirmed_price_text), ''),
    next_action_at = case when p_result_status = 'callback' then p_next_action_at else null end,
    claimed_by = null, claim_expires_at = null,
    assignee_id = coalesce(assignee_id, auth.uid()),
    version = version + 1, updated_by = auth.uid(), updated_at = now()
  where campaign_id = p_campaign_id and venue_id = p_venue_id;
  insert into public.venue_activities (campaign_id, venue_id, activity_type, old_value, new_value, note, created_by)
  values (p_campaign_id, p_venue_id, case when p_is_correction then 'call_correction' else 'call_result' end,
    to_jsonb(cv), private.campaign_venue_json(p_campaign_id, p_venue_id), btrim(p_note), auth.uid());
  response := jsonb_build_object('ok', true, 'code', case when p_is_correction then 'CORRECTED' else 'CALL_COMPLETED' end,
    'campaignVenue', private.campaign_venue_json(p_campaign_id, p_venue_id));
  return private.save_operation(p_operation_id, response);
end;
$$;

create or replace function public.complete_call(
  p_operation_id uuid, p_campaign_id uuid, p_venue_id text, p_result_status text,
  p_availability_text text, p_confirmed_price_text text, p_next_action_at timestamptz, p_note text
)
returns jsonb language sql security definer set search_path = '' as $$
  select private.save_call_result(p_operation_id, p_campaign_id, p_venue_id, p_result_status,
    p_availability_text, p_confirmed_price_text, p_next_action_at, p_note, false);
$$;

create or replace function public.correct_call_result(
  p_operation_id uuid, p_campaign_id uuid, p_venue_id text, p_result_status text,
  p_availability_text text, p_confirmed_price_text text, p_next_action_at timestamptz, p_note text
)
returns jsonb language sql security definer set search_path = '' as $$
  select private.save_call_result(p_operation_id, p_campaign_id, p_venue_id, p_result_status,
    p_availability_text, p_confirmed_price_text, p_next_action_at, p_note, true);
$$;

create or replace function public.update_followup_field(
  p_operation_id uuid,
  p_campaign_id uuid,
  p_venue_id text,
  p_field_name text,
  p_expected_old_value jsonb,
  p_new_value jsonb,
  p_note text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare saved jsonb; problem text; cv public.campaign_venues%rowtype; current_value jsonb; response jsonb; new_assignee uuid;
begin
  saved := private.lock_operation(p_operation_id); if saved is not null then return saved; end if;
  problem := private.lock_active_campaign(p_campaign_id); if problem is not null then return jsonb_build_object('ok', false, 'code', problem); end if;
  if p_field_name not in ('is_shortlisted', 'assignee_id') then return jsonb_build_object('ok', false, 'code', 'FIELD_NOT_ALLOWED'); end if;
  if p_note is not null and length(p_note) > 2000 then return jsonb_build_object('ok', false, 'code', 'NOTE_TOO_LONG'); end if;
  select * into cv from public.campaign_venues where campaign_id = p_campaign_id and venue_id = p_venue_id for update;
  if not found then return jsonb_build_object('ok', false, 'code', 'VENUE_NOT_FOUND'); end if;
  if cv.claimed_by is not null and cv.claim_expires_at > now() and cv.claimed_by <> auth.uid() then return jsonb_build_object('ok', false, 'code', 'CLAIM_CONFLICT'); end if;
  current_value := case when p_field_name = 'is_shortlisted' then to_jsonb(cv.is_shortlisted) else to_jsonb(cv.assignee_id) end;
  if current_value is distinct from coalesce(p_expected_old_value, 'null'::jsonb) then
    return private.save_operation(p_operation_id, jsonb_build_object('ok', false, 'code', 'STALE_WRITE', 'campaignVenue', to_jsonb(cv)));
  end if;
  if p_field_name = 'is_shortlisted' then
    if jsonb_typeof(p_new_value) <> 'boolean' then return jsonb_build_object('ok', false, 'code', 'INVALID_VALUE'); end if;
    update public.campaign_venues set is_shortlisted = (p_new_value #>> '{}')::boolean,
      version = version + 1, updated_by = auth.uid(), updated_at = now()
    where campaign_id = p_campaign_id and venue_id = p_venue_id;
  else
    if p_new_value is null or p_new_value = 'null'::jsonb then new_assignee := null;
    else
      begin new_assignee := (p_new_value #>> '{}')::uuid; exception when invalid_text_representation then return jsonb_build_object('ok', false, 'code', 'INVALID_VALUE'); end;
      if not private.is_active_member(new_assignee) then return jsonb_build_object('ok', false, 'code', 'INVALID_ASSIGNEE'); end if;
    end if;
    update public.campaign_venues set assignee_id = new_assignee,
      version = version + 1, updated_by = auth.uid(), updated_at = now()
    where campaign_id = p_campaign_id and venue_id = p_venue_id;
  end if;
  insert into public.venue_activities (campaign_id, venue_id, activity_type, field_name, old_value, new_value, note, created_by)
  values (p_campaign_id, p_venue_id, 'field_update', p_field_name, current_value, coalesce(p_new_value, 'null'::jsonb), p_note, auth.uid());
  response := jsonb_build_object('ok', true, 'code', 'UPDATED', 'campaignVenue', private.campaign_venue_json(p_campaign_id, p_venue_id));
  return private.save_operation(p_operation_id, response);
end;
$$;

create or replace function public.add_note(p_operation_id uuid, p_campaign_id uuid, p_venue_id text, p_note text)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare saved jsonb; problem text; response jsonb;
begin
  saved := private.lock_operation(p_operation_id); if saved is not null then return saved; end if;
  problem := private.lock_active_campaign(p_campaign_id); if problem is not null then return jsonb_build_object('ok', false, 'code', problem); end if;
  if length(btrim(coalesce(p_note, ''))) = 0 or length(p_note) > 2000 then return jsonb_build_object('ok', false, 'code', 'NOTE_REQUIRED'); end if;
  if not exists (select 1 from public.campaign_venues where campaign_id = p_campaign_id and venue_id = p_venue_id) then return jsonb_build_object('ok', false, 'code', 'VENUE_NOT_FOUND'); end if;
  insert into public.venue_activities (campaign_id, venue_id, activity_type, note, created_by)
  values (p_campaign_id, p_venue_id, 'note', btrim(p_note), auth.uid());
  response := jsonb_build_object('ok', true, 'code', 'NOTE_ADDED', 'campaignVenue', private.campaign_venue_json(p_campaign_id, p_venue_id));
  return private.save_operation(p_operation_id, response);
end;
$$;

revoke all on function private.save_call_result(uuid, uuid, text, text, text, text, timestamptz, text, boolean) from public, anon, authenticated;

revoke all on function public.get_workspace_bootstrap(integer) from public, anon;
revoke all on function public.claim_venue(uuid, uuid, text) from public, anon;
revoke all on function public.renew_claim(uuid, uuid, text) from public, anon;
revoke all on function public.release_claim(uuid, uuid, text) from public, anon;
revoke all on function public.take_over_stale_claim(uuid, uuid, text, uuid, timestamptz) from public, anon;
revoke all on function public.complete_call(uuid, uuid, text, text, text, text, timestamptz, text) from public, anon;
revoke all on function public.correct_call_result(uuid, uuid, text, text, text, text, timestamptz, text) from public, anon;
revoke all on function public.update_followup_field(uuid, uuid, text, text, jsonb, jsonb, text) from public, anon;
revoke all on function public.add_note(uuid, uuid, text, text) from public, anon;

grant execute on function public.get_workspace_bootstrap(integer) to authenticated;
grant execute on function public.claim_venue(uuid, uuid, text) to authenticated;
grant execute on function public.renew_claim(uuid, uuid, text) to authenticated;
grant execute on function public.release_claim(uuid, uuid, text) to authenticated;
grant execute on function public.take_over_stale_claim(uuid, uuid, text, uuid, timestamptz) to authenticated;
grant execute on function public.complete_call(uuid, uuid, text, text, text, text, timestamptz, text) to authenticated;
grant execute on function public.correct_call_result(uuid, uuid, text, text, text, text, timestamptz, text) to authenticated;
grant execute on function public.update_followup_field(uuid, uuid, text, text, jsonb, jsonb, text) to authenticated;
grant execute on function public.add_note(uuid, uuid, text, text) to authenticated;

-- Private Storage bucket: authenticated active members can only download.
insert into storage.buckets (id, name, public, file_size_limit)
values ('venue-datasets', 'venue-datasets', false, 5242880)
on conflict (id) do update set public = false, file_size_limit = excluded.file_size_limit;

drop policy if exists active_members_download_private_release on storage.objects;
create policy active_members_download_private_release on storage.objects
for select to authenticated
using (bucket_id = 'venue-datasets' and private.is_active_member());

-- Realtime is best effort; the web app falls back to a ten-second snapshot poll.
alter table public.campaign_venues replica identity full;
alter table public.venue_activities replica identity full;
do $$
begin
  if not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'campaign_venues') then
    alter publication supabase_realtime add table public.campaign_venues;
  end if;
  if not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'venue_activities') then
    alter publication supabase_realtime add table public.venue_activities;
  end if;
end;
$$;

-- Service-role-only deterministic bootstrap. p_members and p_venues are JSON arrays.
create or replace function public.admin_bootstrap_workspace(
  p_owner_user_id uuid,
  p_members jsonb,
  p_dataset_release_id text,
  p_dataset_manifest_checksum text,
  p_private_manifest jsonb,
  p_venues jsonb,
  p_campaign_name text,
  p_event_date date default null
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare campaign_id uuid; item jsonb; venue_count integer := 0;
begin
  if p_private_manifest->>'release_id' is distinct from p_dataset_release_id
    or p_private_manifest->>'dataset_checksum' is distinct from p_dataset_manifest_checksum then
    raise exception 'Manifest mismatch';
  end if;
  if jsonb_typeof(p_members) <> 'array' or jsonb_typeof(p_venues) <> 'array' then raise exception 'Arrays required'; end if;
  if not exists (select 1 from auth.users where id = p_owner_user_id) then raise exception 'Owner user not found'; end if;
  for item in select value from jsonb_array_elements(p_members)
  loop
    insert into public.workspace_members (user_id, display_name, active, updated_at)
    values ((item->>'user_id')::uuid, btrim(item->>'display_name'), true, now())
    on conflict (user_id) do update set display_name = excluded.display_name, active = true, updated_at = now();
  end loop;
  insert into public.workspace_members (user_id, display_name, active)
  values (p_owner_user_id, coalesce((select raw_user_meta_data->>'display_name' from auth.users where id = p_owner_user_id), 'Anthony'), true)
  on conflict (user_id) do update set active = true, updated_at = now();
  insert into public.campaigns (name, event_date, dataset_release_id, dataset_manifest_checksum, private_manifest, created_by)
  values (p_campaign_name, p_event_date, p_dataset_release_id, p_dataset_manifest_checksum, p_private_manifest, p_owner_user_id)
  returning id into campaign_id;
  for item in select value from jsonb_array_elements(p_venues)
  loop
    insert into public.venue_registry (venue_id, source_fingerprint, active, updated_at)
    values (item->>'id', item->>'source_fingerprint', true, now())
    on conflict (venue_id) do update set source_fingerprint = excluded.source_fingerprint, active = true, updated_at = now();
    insert into public.campaign_venues (campaign_id, venue_id)
    values (campaign_id, item->>'id');
    venue_count := venue_count + 1;
  end loop;
  insert into public.workspace_state (singleton, owner_user_id, active_campaign_id, updated_at)
  values (true, p_owner_user_id, campaign_id, now())
  on conflict (singleton) do update set owner_user_id = excluded.owner_user_id, active_campaign_id = excluded.active_campaign_id, updated_at = now();
  return jsonb_build_object('ok', true, 'campaign_id', campaign_id, 'venue_count', venue_count);
end;
$$;

revoke all on function public.admin_bootstrap_workspace(uuid, jsonb, text, text, jsonb, jsonb, text, date) from public, anon, authenticated;
grant execute on function public.admin_bootstrap_workspace(uuid, jsonb, text, text, jsonb, jsonb, text, date) to service_role;
