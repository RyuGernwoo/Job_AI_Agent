from datetime import datetime, timezone
from uuid import uuid4

from lectureops_agent.models.schemas import LessonPackage, PackageEditPatch, PackageStatus, ReviewEvent, ReviewPatch

_ALLOWED_TRANSITIONS: dict[PackageStatus, set[PackageStatus]] = {
    PackageStatus.DRAFT: {PackageStatus.REVIEWED, PackageStatus.REGENERATED, PackageStatus.NEEDS_REVISION},
    PackageStatus.REGENERATED: {PackageStatus.DRAFT, PackageStatus.REVIEWED},
    PackageStatus.NEEDS_REVISION: {PackageStatus.DRAFT, PackageStatus.REVIEWED},
    PackageStatus.REVIEWED: {PackageStatus.DRAFT, PackageStatus.APPROVED},
    PackageStatus.APPROVED: {PackageStatus.EXPORTED},
    PackageStatus.EXPORTED: set(),
}


def apply_review_patch(package: LessonPackage, patch: ReviewPatch) -> LessonPackage:
    allowed = _ALLOWED_TRANSITIONS[package.status]
    if patch.status not in allowed:
        raise ValueError(f"invalid status transition: {package.status.value} -> {patch.status.value}")
    event = _review_event(
        package=package,
        to_status=patch.status,
        reviewer_notes=patch.reviewer_notes,
        reviewer_name=patch.reviewer_name,
        changed_fields=["status"],
    )
    return package.model_copy(
        update={
            "status": patch.status,
            "reviewer_notes": patch.reviewer_notes,
            "review_history": [*package.review_history, event],
        }
    )


def apply_package_edit(package: LessonPackage, patch: PackageEditPatch) -> LessonPackage:
    updates = {}
    changed_fields: list[str] = []
    if patch.lesson_plan is not None:
        updates["lesson_plan"] = patch.lesson_plan
        changed_fields.append("lesson_plan")
    if patch.practice is not None:
        updates["practice"] = patch.practice
        changed_fields.append("practice")
    if patch.assessment is not None:
        updates["assessment"] = patch.assessment
        changed_fields.append("assessment")
    if not changed_fields:
        raise ValueError("at least one package section must be provided")

    event = _review_event(
        package=package,
        to_status=PackageStatus.DRAFT,
        reviewer_notes=patch.edit_reason,
        reviewer_name=patch.reviewer_name,
        changed_fields=changed_fields,
    )
    updates.update(
        {
            "status": PackageStatus.DRAFT,
            "reviewer_notes": patch.edit_reason,
            "review_history": [*package.review_history, event],
        }
    )
    return package.model_copy(update=updates)


def _review_event(
    *,
    package: LessonPackage,
    to_status: PackageStatus,
    reviewer_notes: str,
    reviewer_name: str | None,
    changed_fields: list[str],
) -> ReviewEvent:
    return ReviewEvent(
        event_id=str(uuid4()),
        package_id=package.package_id,
        from_status=package.status,
        to_status=to_status,
        reviewer_name=reviewer_name,
        reviewer_notes=reviewer_notes,
        changed_fields=changed_fields,
        created_at=datetime.now(timezone.utc),
    )
