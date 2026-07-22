-- LessonPack AI server-owned RAG persistence and versioned embedding support.
-- Apply after 001_lessonpack_vectors.sql and before deploying /rag endpoints.

alter table public.lessonpack_chunks
    add column if not exists scope text not null default 'project',
    add column if not exists embedding_model text not null default 'hash:lessonpack-hash-v1',
    add column if not exists embedding_version text not null default 'v1',
    add column if not exists content_hash text,
    add column if not exists embedding_v2 extensions.vector(1536);

-- New semantic rows may use embedding_v2 only. Existing 64-dimensional rows
-- keep their legacy embedding for compatibility during staged reindexing.
alter table public.lessonpack_chunks
    alter column embedding drop not null;

update public.lessonpack_chunks
set scope = 'baseline'
where project_id = 'mvp-dataset';

alter table public.lessonpack_chunks
    drop constraint if exists lessonpack_chunks_scope_check;

alter table public.lessonpack_chunks
    add constraint lessonpack_chunks_scope_check
    check (scope in ('project', 'baseline'));

create index if not exists lessonpack_chunks_scope_idx
    on public.lessonpack_chunks (scope, project_id);

create index if not exists lessonpack_chunks_embedding_v2_hnsw_idx
    on public.lessonpack_chunks
    using hnsw (embedding_v2 vector_cosine_ops)
    where embedding_v2 is not null;

create table if not exists public.lessonpack_projects (
    project_id text primary key,
    course_title text not null,
    lesson_title text not null,
    learner_profile text not null,
    learning_objectives jsonb not null default '[]'::jsonb,
    ncs_units jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists public.lessonpack_documents (
    document_id text primary key,
    project_id text not null references public.lessonpack_projects(project_id) on delete cascade,
    source_name text not null,
    source_type text not null,
    content_hash text not null,
    chunk_count integer not null check (chunk_count > 0),
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    unique (project_id, content_hash)
);

create table if not exists public.lessonpack_retrieval_runs (
    run_id text primary key,
    trace_id text not null,
    project_id text not null references public.lessonpack_projects(project_id) on delete cascade,
    query text not null,
    normalized_query text not null,
    evidence jsonb not null default '[]'::jsonb,
    selected_chunk_ids jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists public.lessonpack_generation_runs (
    package_id text primary key,
    project_id text not null references public.lessonpack_projects(project_id) on delete cascade,
    retrieval_run_id text not null references public.lessonpack_retrieval_runs(run_id) on delete restrict,
    trace_id text not null,
    provider_name text not null,
    structured_output_applied boolean not null default false,
    citation_ids jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists lessonpack_documents_project_id_idx
    on public.lessonpack_documents (project_id, created_at desc);

create index if not exists lessonpack_retrieval_runs_project_id_idx
    on public.lessonpack_retrieval_runs (project_id, created_at desc);

create index if not exists lessonpack_generation_runs_project_id_idx
    on public.lessonpack_generation_runs (project_id, created_at desc);

alter table public.lessonpack_projects enable row level security;
alter table public.lessonpack_documents enable row level security;
alter table public.lessonpack_retrieval_runs enable row level security;
alter table public.lessonpack_generation_runs enable row level security;

-- Exact project filtering prevents a global HNSW scan from returning candidates
-- from other projects and then dropping all of them after the project filter.
create or replace function public.match_lessonpack_chunks (
    query_embedding extensions.vector(64),
    match_project_id text,
    match_count integer default 5,
    match_threshold double precision default 0
)
returns table (
    chunk_id text,
    project_id text,
    document_id text,
    source_name text,
    source_type text,
    page integer,
    content text,
    metadata jsonb,
    similarity double precision
)
language plpgsql
stable
as $function$
begin
    return query execute $query$
        select
            c.chunk_id,
            c.project_id,
            c.document_id,
            c.source_name,
            c.source_type,
            c.page,
            c.content,
            c.metadata,
            1 - (c.embedding <=> $1) as similarity
        from public.lessonpack_chunks c
        where c.project_id = $2
          and c.embedding is not null
          and 1 - (c.embedding <=> $1) >= $4
        order by c.embedding <=> $1
        limit least($3, 200)
    $query$ using query_embedding, match_project_id, match_count, match_threshold;
end;
$function$;

create or replace function public.match_lessonpack_chunks_v2 (
    query_embedding extensions.vector(1536),
    match_project_id text,
    match_count integer default 20,
    match_threshold double precision default 0
)
returns table (
    chunk_id text,
    project_id text,
    document_id text,
    source_name text,
    source_type text,
    page integer,
    content text,
    metadata jsonb,
    similarity double precision
)
language plpgsql
stable
as $function$
begin
    return query execute $query$
        select
            c.chunk_id,
            c.project_id,
            c.document_id,
            c.source_name,
            c.source_type,
            c.page,
            c.content,
            c.metadata,
            1 - (c.embedding_v2 <=> $1) as similarity
        from public.lessonpack_chunks c
        where c.project_id = $2
          and c.embedding_v2 is not null
          and 1 - (c.embedding_v2 <=> $1) >= $4
        order by c.embedding_v2 <=> $1
        limit least($3, 200)
    $query$ using query_embedding, match_project_id, match_count, match_threshold;
end;
$function$;
