-- Store one active user-provided PPTX template per LessonPack project.
-- The private Storage bucket is accessed only by the backend service role.

insert into storage.buckets (
    id,
    name,
    public,
    file_size_limit,
    allowed_mime_types
)
values (
    'lessonpack-ppt-templates',
    'lessonpack-ppt-templates',
    false,
    26214400,
    array[
        'application/vnd.openxmlformats-officedocument.presentationml.presentation'
    ]
)
on conflict (id) do update
set
    public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

create table if not exists public.lessonpack_ppt_templates (
    template_id text primary key,
    project_id text not null unique
        references public.lessonpack_projects(project_id) on delete cascade,
    storage_path text not null unique,
    original_filename text not null,
    content_hash text not null check (char_length(content_hash) = 64),
    file_size_bytes bigint not null check (file_size_bytes > 0),
    source_slide_count integer not null default 0 check (source_slide_count >= 0),
    slide_width bigint not null check (slide_width > 0),
    slide_height bigint not null check (slide_height > 0),
    layout_manifest jsonb not null default '[]'::jsonb,
    layout_mapping jsonb not null default '{}'::jsonb,
    warnings jsonb not null default '[]'::jsonb,
    status text not null default 'ready' check (status = 'ready'),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint lessonpack_ppt_layout_manifest_array
        check (jsonb_typeof(layout_manifest) = 'array'),
    constraint lessonpack_ppt_layout_mapping_object
        check (jsonb_typeof(layout_mapping) = 'object'),
    constraint lessonpack_ppt_warnings_array
        check (jsonb_typeof(warnings) = 'array')
);

create index if not exists lessonpack_ppt_templates_project_idx
    on public.lessonpack_ppt_templates (project_id);

alter table public.lessonpack_ppt_templates enable row level security;

comment on table public.lessonpack_ppt_templates is
    'Private PPTX template metadata. Template binaries are stored in the lessonpack-ppt-templates bucket.';
