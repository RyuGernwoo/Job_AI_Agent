-- Restore HNSW-backed vector retrieval after the NCS baseline expansion.
-- The earlier functions disabled index scans, which becomes prohibitively slow
-- once the baseline contains thousands of 1536-dimensional vectors.

create index if not exists lessonpack_chunks_embedding_hnsw_idx
    on public.lessonpack_chunks
    using hnsw (embedding vector_cosine_ops)
    where embedding is not null;

create index if not exists lessonpack_chunks_embedding_v2_hnsw_idx
    on public.lessonpack_chunks
    using hnsw (embedding_v2 vector_cosine_ops)
    where embedding_v2 is not null;

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

analyze public.lessonpack_chunks;
