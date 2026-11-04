"""Read friction through the shared repository API."""

from __future__ import annotations

from varde_data.repos.friction import FrictionRepository

from .. import friction_repository
from ..errors import StoreItemNotFound
from .types import (
    FrictionExportItem,
    FrictionItem,
    FrictionListRequest,
    FrictionRecurrence,
    FrictionRecurrenceReport,
    FrictionShow,
    PageRequest,
    StorePage,
    normalize_scope_path,
    require_nonblank,
    validate_page,
    validate_tag,
)


def _get_item(repository: FrictionRepository, item_id: int) -> FrictionItem:
    return _get_item_by_identifier(repository, str(item_id))


def _get_item_by_identifier(
    repository: FrictionRepository, identifier: str
) -> FrictionItem:
    try:
        record = friction_repository.show(repository, identifier).item
    except Exception as error:
        if getattr(error, "code", None) in {"not_found", "item_not_found"}:
            raise StoreItemNotFound(identifier) from error
        raise
    return friction_repository.item(repository, record)


def list_items(
    repository: FrictionRepository, request: FrictionListRequest
) -> StorePage[FrictionItem]:
    validate_page(request.page)
    if request.global_ and request.repo_root is not None:
        raise ValueError("--repo and --global cannot be combined")
    if request.source is not None:
        require_nonblank(request.source, "source")
    if request.text is not None:
        require_nonblank(request.text, "text")
    if request.tag is not None:
        validate_tag(request.tag)
    filters = {
        "status": request.status.as_str() if request.status is not None else None,
        "source": request.source,
        "repo_root": (
            str(normalize_scope_path(request.repo_root, request.cwd))
            if request.repo_root is not None
            else None
        ),
        "global_": request.global_,
        "tag": request.tag,
        "text": request.text,
    }
    first_page = repository.list_items(**filters, offset=0, limit=1_000)
    numbers = friction_repository.EventNumbers.from_repository(repository)
    records = list(first_page.items)
    for offset in range(1_000, first_page.total, 1_000):
        records.extend(
            repository.list_items(**filters, offset=offset, limit=1_000).items
        )
    records.sort(
        key=lambda record: friction_repository.item_identifier(
            repository, record, numbers
        )
    )
    selected = records[request.page.offset : request.page.offset + request.page.limit]
    items = [
        friction_repository.item(repository, record, numbers) for record in selected
    ]
    return StorePage.new(items, first_page.total, request.page)


def show_friction(
    repository: FrictionRepository, identifier: str, page: PageRequest
) -> FrictionShow:
    validate_page(page)
    require_nonblank(identifier, "identifier")
    result = friction_repository.show(
        repository, identifier, offset=page.offset, limit=page.limit
    )
    numbers = friction_repository.EventNumbers.from_repository(repository)
    return FrictionShow(
        friction_repository.item(repository, result.item, numbers),
        StorePage.new(
            [
                friction_repository.occurrence(repository, value, numbers)
                for value in result.occurrences.items
            ],
            result.occurrences.total,
            page,
        ),
        StorePage.new(
            [
                friction_repository.status_change(repository, value, numbers)
                for value in result.status_changes.items
            ],
            result.status_changes.total,
            page,
        ),
    )


def export_items(repository: FrictionRepository) -> list[FrictionExportItem]:
    numbers = friction_repository.EventNumbers.from_repository(repository)
    return [
        FrictionExportItem(
            friction_repository.item(repository, value.item, numbers),
            [
                friction_repository.occurrence(repository, item, numbers)
                for item in value.occurrences
            ],
            [
                friction_repository.status_change(repository, item, numbers)
                for item in value.status_changes
            ],
        )
        for value in repository.export_items()
    ]


def list_recurrences(
    repository: FrictionRepository, page: PageRequest
) -> FrictionRecurrenceReport:
    validate_page(page)
    report = repository.list_recurrences(offset=page.offset, limit=page.limit)
    numbers = friction_repository.EventNumbers.from_repository(repository)
    result = report.page
    return FrictionRecurrenceReport(
        StorePage.new(
            [
                FrictionRecurrence(
                    friction_repository.adoption_id(
                        repository, value.adoption, numbers
                    ),
                    value.adoption.at,
                    value.adoption.summary,
                    friction_repository.item(repository, value.item, numbers),
                    friction_repository.occurrence(
                        repository, value.occurrence, numbers
                    ),
                )
                for value in result.items
            ],
            result.total,
            page,
        ),
        report.skipped_invalid_timestamps,
    )
