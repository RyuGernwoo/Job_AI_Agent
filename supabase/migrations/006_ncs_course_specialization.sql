-- Add explicit NCS/general course modes and a structured NCS catalog.
-- Apply after 005_project_retrieval_queries.sql before deploying this API version.

alter table public.lessonpack_projects
    add column if not exists course_type text;

update public.lessonpack_projects
set course_type = case
    when jsonb_array_length(ncs_units) > 0 then 'ncs'
    else 'general'
end
where course_type is null;

alter table public.lessonpack_projects
    alter column course_type set default 'general',
    alter column course_type set not null;

alter table public.lessonpack_projects
    drop constraint if exists lessonpack_projects_course_type_check,
    drop constraint if exists lessonpack_projects_ncs_payload_check;

alter table public.lessonpack_projects
    add constraint lessonpack_projects_course_type_check
        check (course_type in ('ncs', 'general')),
    add constraint lessonpack_projects_ncs_payload_check
        check (
            (course_type = 'ncs' and jsonb_array_length(ncs_units) between 1 and 5)
            or (course_type = 'general' and jsonb_array_length(ncs_units) = 0)
        );

alter table public.lessonpack_retrieval_runs
    add column if not exists course_type text not null default 'general',
    add column if not exists ncs_unit_codes jsonb not null default '[]'::jsonb,
    add column if not exists catalog_versions jsonb not null default '[]'::jsonb;

update public.lessonpack_retrieval_runs as retrieval
set
    course_type = project.course_type,
    ncs_unit_codes = coalesce(
        (
            select jsonb_agg(unit ->> 'unit_code')
            from jsonb_array_elements(project.ncs_units) as items(unit)
            where coalesce(unit ->> 'unit_code', '') <> ''
        ),
        '[]'::jsonb
    ),
    catalog_versions = coalesce(
        (
            select jsonb_agg(distinct unit ->> 'catalog_version')
            from jsonb_array_elements(project.ncs_units) as items(unit)
            where coalesce(unit ->> 'catalog_version', '') <> ''
        ),
        '[]'::jsonb
    )
from public.lessonpack_projects as project
where project.project_id = retrieval.project_id;

alter table public.lessonpack_retrieval_runs
    drop constraint if exists lessonpack_retrieval_runs_course_type_check;

alter table public.lessonpack_retrieval_runs
    add constraint lessonpack_retrieval_runs_course_type_check
        check (course_type in ('ncs', 'general'));

create table if not exists public.lessonpack_ncs_catalog (
    unit_code text primary key,
    unit_name text not null,
    definition text,
    classification jsonb not null default '{}'::jsonb,
    level integer check (level between 1 and 8),
    catalog_version text,
    source_url text,
    criteria jsonb not null default '[]'::jsonb,
    source_hash text,
    imported_at timestamptz not null default now()
);

create table if not exists public.lessonpack_ncs_criteria (
    criterion_code text primary key,
    unit_code text not null references public.lessonpack_ncs_catalog(unit_code) on delete cascade,
    element_code text,
    element_name text,
    criterion_text text not null,
    knowledge jsonb not null default '[]'::jsonb,
    skills jsonb not null default '[]'::jsonb,
    attitudes jsonb not null default '[]'::jsonb,
    assessment_guidance jsonb not null default '[]'::jsonb
);

create index if not exists lessonpack_ncs_catalog_name_idx
    on public.lessonpack_ncs_catalog (unit_name);

create index if not exists lessonpack_ncs_criteria_unit_code_idx
    on public.lessonpack_ncs_criteria (unit_code);

alter table public.lessonpack_ncs_catalog enable row level security;
alter table public.lessonpack_ncs_criteria enable row level security;
