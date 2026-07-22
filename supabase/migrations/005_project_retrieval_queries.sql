-- Persist the user-defined RAG queries entered with each lesson project.
-- Apply after 004_vector_search_performance.sql before deploying this API version.

alter table public.lessonpack_projects
    add column if not exists retrieval_queries jsonb not null default '[]'::jsonb;

alter table public.lessonpack_projects
    drop constraint if exists lessonpack_projects_retrieval_queries_type_check,
    drop constraint if exists lessonpack_projects_retrieval_queries_count_check;

alter table public.lessonpack_projects
    add constraint lessonpack_projects_retrieval_queries_type_check
        check (jsonb_typeof(retrieval_queries) = 'array'),
    add constraint lessonpack_projects_retrieval_queries_count_check
        check (jsonb_array_length(retrieval_queries) <= 5);
