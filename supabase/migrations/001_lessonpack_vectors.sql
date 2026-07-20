-- LessonPack AI Supabase vector store schema.
-- Run this in Supabase SQL Editor before setting LECTUREOPS_VECTOR_STORE=supabase.

create extension if not exists vector with schema extensions;

create table if not exists public.lessonpack_chunks (
    chunk_id text primary key,
    project_id text not null,
    document_id text not null,
    source_name text not null,
    source_type text not null default 'txt',
    page integer,
    content text not null,
    metadata jsonb not null default '{}'::jsonb,
    embedding extensions.vector(64) not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists lessonpack_chunks_project_id_idx
    on public.lessonpack_chunks (project_id);

create index if not exists lessonpack_chunks_embedding_hnsw_idx
    on public.lessonpack_chunks
    using hnsw (embedding vector_cosine_ops);

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
language sql
stable
as $$
    select
        c.chunk_id,
        c.project_id,
        c.document_id,
        c.source_name,
        c.source_type,
        c.page,
        c.content,
        c.metadata,
        1 - (c.embedding <=> query_embedding) as similarity
    from public.lessonpack_chunks c
    where c.project_id = match_project_id
      and 1 - (c.embedding <=> query_embedding) >= match_threshold
    order by c.embedding <=> query_embedding
    limit least(match_count, 200);
$$;
