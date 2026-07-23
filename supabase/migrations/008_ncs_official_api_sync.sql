-- Persist official NCS API source records, resumable sync runs, and module summaries.
-- Apply after 007_ncs_catalog_search.sql before enabling the scheduled sync workflow.

alter table public.lessonpack_ncs_catalog
    add column if not exists official_synced_at timestamptz,
    add column if not exists official_source_hash text;

create table if not exists public.lessonpack_ncs_sync_runs (
    run_id text primary key,
    mode text not null check (mode in ('catalog', 'detail', 'modules', 'all')),
    status text not null check (status in ('running', 'partial', 'completed', 'failed')),
    checkpoint jsonb not null default '{}'::jsonb,
    request_count integer not null default 0 check (request_count >= 0),
    received_count integer not null default 0 check (received_count >= 0),
    changed_count integer not null default 0 check (changed_count >= 0),
    chunk_upsert_count integer not null default 0 check (chunk_upsert_count >= 0),
    error_count integer not null default 0 check (error_count >= 0),
    error_summary text,
    started_at timestamptz not null default now(),
    finished_at timestamptz
);

create table if not exists public.lessonpack_ncs_source_records (
    source_key text primary key,
    operation text not null,
    partition_key text not null,
    entity_type text not null,
    unit_code text,
    payload jsonb not null,
    payload_hash text not null,
    embedded_payload_hash text,
    chunk_ids jsonb not null default '[]'::jsonb,
    fetched_at timestamptz not null,
    active boolean not null default true,
    last_run_id text references public.lessonpack_ncs_sync_runs(run_id) on delete set null,
    constraint lessonpack_ncs_source_chunk_ids_array
        check (jsonb_typeof(chunk_ids) = 'array')
);

create table if not exists public.lessonpack_ncs_modules (
    module_id text primary key,
    module_name text not null,
    module_text text not null default '',
    classification jsonb not null default '{}'::jsonb,
    unit_code text,
    link_status text not null default 'unresolved'
        check (link_status in ('exact', 'candidate', 'unresolved')),
    source_url text not null,
    payload_hash text not null,
    fetched_at timestamptz not null
);

create index if not exists lessonpack_ncs_sync_runs_status_idx
    on public.lessonpack_ncs_sync_runs (status, started_at desc);

create index if not exists lessonpack_ncs_source_operation_idx
    on public.lessonpack_ncs_source_records (operation, partition_key, unit_code);

create index if not exists lessonpack_ncs_source_payload_hash_idx
    on public.lessonpack_ncs_source_records (payload_hash);

create index if not exists lessonpack_ncs_modules_name_idx
    on public.lessonpack_ncs_modules (module_name);

create index if not exists lessonpack_ncs_modules_unit_code_idx
    on public.lessonpack_ncs_modules (unit_code)
    where unit_code is not null;

alter table public.lessonpack_ncs_sync_runs enable row level security;
alter table public.lessonpack_ncs_source_records enable row level security;
alter table public.lessonpack_ncs_modules enable row level security;

comment on table public.lessonpack_ncs_source_records is
    'Normalized raw records fetched from official HRDKorea NCS APIs. Service-role access only.';

comment on column public.lessonpack_ncs_source_records.embedded_payload_hash is
    'Payload hash represented by the current RAG chunk_ids. A mismatch requires re-embedding.';

comment on table public.lessonpack_ncs_modules is
    'Official NCS learning-module metadata and summary content; not the full PDF/HWP module.';
