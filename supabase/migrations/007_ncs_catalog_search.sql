-- Optimize partial searches across the complete official NCS unit catalog.
-- Apply after 006_ncs_course_specialization.sql.

create extension if not exists pg_trgm with schema extensions;

create index if not exists lessonpack_ncs_catalog_unit_code_trgm_idx
    on public.lessonpack_ncs_catalog
    using gin (unit_code extensions.gin_trgm_ops);

create index if not exists lessonpack_ncs_catalog_unit_name_trgm_idx
    on public.lessonpack_ncs_catalog
    using gin (unit_name extensions.gin_trgm_ops);

comment on table public.lessonpack_ncs_catalog is
    'Complete official NCS unit code/name catalog. An empty criteria array means LessonPack RAG details are not loaded yet.';
