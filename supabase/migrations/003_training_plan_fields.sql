-- Persist user-provided training schedule and delivery ratios.
-- Apply after 002_rag_persistence.sql before deploying the matching API version.

alter table public.lessonpack_projects
    add column if not exists total_training_hours numeric(8, 2) not null default 2,
    add column if not exists total_lessons integer not null default 1,
    add column if not exists theory_ratio_percent integer not null default 30,
    add column if not exists practice_ratio_percent integer not null default 70;

alter table public.lessonpack_projects
    drop constraint if exists lessonpack_projects_training_hours_check,
    drop constraint if exists lessonpack_projects_total_lessons_check,
    drop constraint if exists lessonpack_projects_theory_ratio_check,
    drop constraint if exists lessonpack_projects_practice_ratio_check,
    drop constraint if exists lessonpack_projects_ratio_total_check,
    drop constraint if exists lessonpack_projects_average_lesson_duration_check;

alter table public.lessonpack_projects
    add constraint lessonpack_projects_training_hours_check
        check (total_training_hours > 0),
    add constraint lessonpack_projects_total_lessons_check
        check (total_lessons > 0),
    add constraint lessonpack_projects_theory_ratio_check
        check (theory_ratio_percent between 0 and 100),
    add constraint lessonpack_projects_practice_ratio_check
        check (practice_ratio_percent between 0 and 100),
    add constraint lessonpack_projects_ratio_total_check
        check (theory_ratio_percent + practice_ratio_percent = 100),
    add constraint lessonpack_projects_average_lesson_duration_check
        check (total_training_hours * 60 / total_lessons >= 15);
