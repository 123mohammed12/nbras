"""Execution and orchestration runner for ContentBatchImporter in Operations Console (/control/)."""

from __future__ import annotations

import uuid
from typing import Any

from django.core.cache import cache
from django.core.exceptions import ValidationError

from apps.imports.models import ContentImportLog, ImportStatus
from apps.imports.services.content_importer import (
    ContentBatchImporter,
    ContentImportError,
    ImportSource,
)

PREVIEW_CACHE_PREFIX = "content-import"
PREVIEW_CACHE_TTL = 900  # 15 minutes


def stage_import_preview(
    *,
    user: Any,
    sources: list[ImportSource],
    content_type: str,
    operation: str,
    checksum: str,
    report: dict,
) -> str:
    """Stages validated import payload in cache for non-destructive preview and confirmation."""
    confirm_token = uuid.uuid4().hex
    cache.set(
        f"{PREVIEW_CACHE_PREFIX}:{confirm_token}",
        {
            "user_id": user.pk,
            "content_type": content_type,
            "operation": operation,
            "checksum": checksum,
            "sources": [{"name": item.name, "content": item.content} for item in sources],
            "report": report,
        },
        timeout=PREVIEW_CACHE_TTL,
    )
    return confirm_token


def get_staged_import(token: str, user: Any = None) -> dict | None:
    """Retrieves staged import payload if valid and unexpired."""
    staged = cache.get(f"{PREVIEW_CACHE_PREFIX}:{token}")
    if not staged:
        return None
    if user is not None:
        user_matches = (
            staged.get("user_id") == user.pk
            or getattr(user, "is_superuser", False)
        )
        if not user_matches:
            return None
    return staged


def execute_staged_import(
    *,
    token: str,
    user: Any,
    replace_scope_confirmed: bool = False,
) -> tuple[ContentImportLog, dict]:
    """Atomically executes a staged import batch with double-submit and race condition guards."""
    lock_key = f"{PREVIEW_CACHE_PREFIX}-lock:{token}"

    # Atomic lock prevents duplicate concurrent execution (e.g. double-click or rapid duplicate POST)
    acquired = cache.add(lock_key, "executing", timeout=60)
    if not acquired:
        raise ContentImportError("هذا الاستيراد قيد المعالجة الآن؛ يرجى الانتظار وتجنب التقديم المتكرر.")

    try:
        staged = get_staged_import(token, user)
        if not staged:
            raise ContentImportError("انتهت صلاحية المعاينة (المهلة 15 دقيقة)؛ أعد رفع الملفات والتحقق منها قبل التنفيذ.")

        operation = staged["operation"]
        if operation == "replace_scope" and not replace_scope_confirmed:
            raise ContentImportError("عملية استبدال النطاق تتطلب تأكيداً صريحاً وموافقة على استبدال المحتوى.")

        sources = [ImportSource(item["name"], item["content"]) for item in staged["sources"]]
        importer = ContentBatchImporter(
            sources,
            requested_type=staged["content_type"],
            operation=operation,
        )

        try:
            report = importer.execute()
            status = ImportStatus.SUCCEEDED
        except (ContentImportError, ValidationError, OSError, ValueError) as exc:
            error_list = exc.messages if isinstance(exc, ValidationError) else [str(exc)]
            report = {"errors": error_list, "failed": len(error_list)}
            status = ImportStatus.FAILED

        inferred_type = report.get("content_type") or (
            staged["content_type"] if staged["content_type"] != "auto" else "mixed"
        )
        log = ContentImportLog.objects.create(
            content_type=inferred_type,
            operation=operation,
            status=status,
            source_names=[item["name"] for item in staged["sources"]],
            source_checksum=staged.get("checksum", ""),
            report=report,
            errors=report.get("errors", []),
            warnings=report.get("warnings", []),
            created_by=user,
        )

        if status == ImportStatus.SUCCEEDED:
            # Delete confirmation token so it cannot be reused
            cache.delete(f"{PREVIEW_CACHE_PREFIX}:{token}")

        return log, report

    finally:
        cache.delete(lock_key)
