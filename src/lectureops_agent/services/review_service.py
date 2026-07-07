from lectureops_agent.models.schemas import LessonPackage, PackageStatus, ReviewPatch

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
    return package.model_copy(update={"status": patch.status})
