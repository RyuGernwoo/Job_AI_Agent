-- Store only the keys required to fetch selected NCS unit details.
-- Full catalog records stay relational and are not duplicated as raw RAG payloads.

alter table public.lessonpack_ncs_catalog
    add column if not exists duty_code text,
    add column if not exists component_code text;

create index if not exists lessonpack_ncs_catalog_duty_component_idx
    on public.lessonpack_ncs_catalog (duty_code, component_code);

comment on column public.lessonpack_ncs_catalog.duty_code is
    'Official dutyCd used only for on-demand detail synchronization.';

comment on column public.lessonpack_ncs_catalog.component_code is
    'Official compUnitCd used only for on-demand detail synchronization.';
