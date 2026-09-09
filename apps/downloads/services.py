"""Access-aware, versioned unit-pack manifests for intentional downloads.

The pack is deliberately a collection of independently downloadable resources,
not a server-built archive.  This keeps downloads resumable and lets clients
update only resources whose checksum changed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from apps.content.models import ContentLink, FlashcardDeck, Summary
from apps.curriculum.models import ContentStatus, StudyEnrollment, Subject, Unit
from apps.entitlements.services.access_service import AccessContext, evaluate_access_with_context


PACK_SCHEMA_VERSION = 1
PAID_OFFLINE_LEASE_DAYS = 14


class PackUnavailable(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def calculate_file_checksum(file_field) -> tuple[int, str] | None:
    if not file_field or not file_field.name:
        return None
    try:
        size = int(file_field.size)
        modified = None
        try:
            modified = file_field.storage.get_modified_time(file_field.name).timestamp()
        except (AttributeError, NotImplementedError, OSError):
            pass
        key = f"fe10:file-sha256:{file_field.name}:{size}:{modified}"
        checksum = cache.get(key)
        if checksum:
            return size, checksum
        digest = hashlib.sha256()
        with file_field.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        checksum = digest.hexdigest()
        cache.set(key, checksum, 24 * 60 * 60)
        return size, checksum
    except (FileNotFoundError, OSError, ValueError):
        return None


def _iso(value):
    return value.isoformat() if value else None


def _unit_payload(unit: Unit) -> dict[str, Any]:
    lessons = list(
        unit.lessons.filter(status=ContentStatus.PUBLISHED)
        .select_related("explanation")
        .order_by("sort_order", "id")
    )
    summaries = list(
        Summary.objects.filter(unit=unit, status=ContentStatus.PUBLISHED)
        .select_related("lesson")
        .order_by("sort_order", "id")
    )
    decks = list(
        FlashcardDeck.objects.filter(unit=unit, status=ContentStatus.PUBLISHED)
        .select_related("lesson")
        .prefetch_related("cards")
        .order_by("sort_order", "id")
    )
    links = list(
        ContentLink.objects.filter(unit=unit, status=ContentStatus.PUBLISHED)
        .select_related("lesson")
        .order_by("sort_order", "id")
    )
    return {
        "schema_version": PACK_SCHEMA_VERSION,
        "unit": {
            "id": str(unit.id),
            "subject_id": str(unit.subject_id),
            "title": unit.title,
            "description": unit.description,
            "sort_order": unit.sort_order,
            "published_at": _iso(unit.published_at),
        },
        "lessons": [
            {
                "id": str(lesson.id),
                "title": lesson.title,
                "description": lesson.description,
                "estimated_minutes": lesson.estimated_minutes,
                "sort_order": lesson.sort_order,
                "published_at": _iso(lesson.published_at),
                "explanation": (
                    {
                        "id": str(lesson.explanation.id),
                        "title": lesson.explanation.title,
                        "body": lesson.explanation.body,
                        "content_format": lesson.explanation.content_format,
                        "version": lesson.explanation.version,
                    }
                    if hasattr(lesson, "explanation")
                    and lesson.explanation.status == ContentStatus.PUBLISHED
                    else None
                ),
            }
            for lesson in lessons
        ],
        "summaries": [
            {
                "id": str(item.id),
                "title": item.title,
                "summary_type": item.summary_type,
                "lesson_id": str(item.lesson_id) if item.lesson_id else None,
                "body": item.body,
                "version": item.version,
                "sort_order": item.sort_order,
                "has_file": bool(item.file_path and item.is_downloadable),
            }
            for item in summaries
        ],
        "smart_card_decks": [
            {
                "id": str(deck.id),
                "title": deck.title,
                "description": deck.description,
                "lesson_id": str(deck.lesson_id) if deck.lesson_id else None,
                "sort_order": deck.sort_order,
                "cards": [
                    {
                        "id": str(card.id),
                        "front_text": card.front_text,
                        "back_text": card.back_text,
                        "explanation": card.explanation,
                        "difficulty": card.difficulty,
                        "sort_order": card.sort_order,
                    }
                    for card in deck.cards.all()
                    if card.is_active
                ],
            }
            for deck in decks
        ],
        "references": [
            {
                "id": str(link.id),
                "title": link.title,
                "description": link.description,
                "link_type": link.link_type,
                "lesson_id": str(link.lesson_id) if link.lesson_id else None,
                "duration_seconds": link.duration_seconds,
                "sort_order": link.sort_order,
                "external_url": link.url if link.is_external else None,
            }
            for link in links
            if link.link_type != "video"
        ],
    }


@dataclass(frozen=True)
class _Media:
    identity: str
    media_type: str
    resource_id: str
    version: str
    file_field: Any
    mime_type: str


def _media_resources(unit: Unit) -> list[_Media]:
    media: list[_Media] = []
    for summary in Summary.objects.filter(
        unit=unit,
        status=ContentStatus.PUBLISHED,
        is_downloadable=True,
    ):
        if summary.file_path:
            media.append(_Media(
                f"summary-file:{summary.id}", "summary_file", str(summary.id),
                str(summary.version), summary.file_path,
                summary.mime_type or "application/octet-stream",
            ))
    for deck in FlashcardDeck.objects.filter(
        unit=unit, status=ContentStatus.PUBLISHED,
    ).prefetch_related("cards"):
        for card in deck.cards.all():
            if not card.is_active:
                continue
            if card.front_image_path:
                media.append(_Media(
                    f"flashcard-front:{card.id}", "flashcard_front_image",
                    str(card.id), _iso(card.updated_at) or "1",
                    card.front_image_path, "image/*",
                ))
            if card.back_image_path:
                media.append(_Media(
                    f"flashcard-back:{card.id}", "flashcard_back_image",
                    str(card.id), _iso(card.updated_at) or "1",
                    card.back_image_path, "image/*",
                ))
    for link in ContentLink.objects.filter(unit=unit, status=ContentStatus.PUBLISHED):
        # Video is intentionally excluded from FE-10.
        if link.link_type == "video":
            continue
        if link.thumbnail_path:
            media.append(_Media(
                f"link-thumbnail:{link.id}", "content_link_thumbnail",
                str(link.id), _iso(link.updated_at) or "1", link.thumbnail_path,
                "image/*",
            ))
        if link.attached_file_path:
            media.append(_Media(
                f"link-file:{link.id}", "content_link_file", str(link.id),
                _iso(link.updated_at) or "1", link.attached_file_path,
                "application/octet-stream",
            ))
    return media


def _lease(decision, enrollment: StudyEnrollment) -> dict[str, Any]:
    now = timezone.now()
    if decision.allowed and decision.source.startswith("free"):
        return {
            "kind": "free",
            "issued_at": now.isoformat(),
            "offline_until": None,
            "server_time": now.isoformat(),
        }
    upper_bounds = [now + timedelta(days=PAID_OFFLINE_LEASE_DAYS)]
    if decision.expires_at:
        upper_bounds.append(decision.expires_at)
    if enrollment.academic_year_id and enrollment.academic_year.ends_at:
        upper_bounds.append(enrollment.academic_year.ends_at)
    return {
        "kind": "paid",
        "issued_at": now.isoformat(),
        "offline_until": min(upper_bounds).isoformat(),
        "server_time": now.isoformat(),
    }


def _known_unit_access_data(unit: Unit) -> dict[str, Any]:
    return {
        "is_published": unit.status == ContentStatus.PUBLISHED,
        "applies_free_unit": True,
        "scope": {
            "grade_id": str(unit.subject.grade_id),
            "section_id": str(unit.subject.section_id),
            "subject_id": str(unit.subject_id),
            "unit_id": str(unit.id),
            "lesson_id": None,
            "assessment_id": None,
        },
    }


def _build_unit_manifest(*, request, unit, enrollment, context, decision=None):
    decision = decision or evaluate_access_with_context(
        context, "unit", unit.id, _known_unit_access_data(unit),
    )
    if not decision.allowed:
        raise PackUnavailable(decision.reason_code)

    payload = _unit_payload(unit)
    payload_bytes = _canonical_bytes(payload)
    payload_checksum = _sha256_bytes(payload_bytes)
    payload_url = request.build_absolute_uri(
        reverse("downloads:unit-payload", kwargs={"unit_id": unit.id})
        + f"?checksum={payload_checksum}"
    )
    resources = [{
        "id": "unit-payload",
        "type": "unit_payload",
        "version": payload_checksum,
        "bytes": len(payload_bytes),
        "checksum": payload_checksum,
        "url": payload_url,
        "mime_type": "application/json",
    }]
    for item in _media_resources(unit):
        file_info = calculate_file_checksum(item.file_field)
        if not file_info:
            continue
        size, checksum = file_info
        resources.append({
            "id": item.identity,
            "type": item.media_type,
            "version": item.version,
            "bytes": size,
            "checksum": checksum,
            "url": request.build_absolute_uri(reverse(
                "media_access:resource-media",
                kwargs={"resource_type": item.media_type, "resource_id": item.resource_id},
            )),
            "mime_type": item.mime_type,
        })
    version_material = [
        f"{item['id']}:{item['version']}:{item['checksum']}" for item in resources
    ]
    content_version = _sha256_bytes("\n".join(version_material).encode("utf-8"))[:24]
    return {
        "pack_id": f"unit:{unit.id}",
        "unit_id": str(unit.id),
        "unit_title": unit.title,
        "subject_id": str(unit.subject_id),
        "subject_title": unit.subject.name_ar,
        "academic_context": {
            "enrollment_id": str(enrollment.id),
            "academic_year_id": str(enrollment.academic_year_id or ""),
            "grade_id": str(enrollment.grade_id),
            "section_id": str(enrollment.section_id),
        },
        "content_version": content_version,
        "schema_version": PACK_SCHEMA_VERSION,
        "total_bytes": sum(item["bytes"] for item in resources),
        "resource_count": len(resources),
        "resources": resources,
        "created_at": timezone.now().isoformat(),
        "published_at": _iso(unit.published_at),
        "access": decision.to_dict(),
        "offline_access_lease": _lease(decision, enrollment),
    }


def build_unit_manifest(*, request, unit_id: str) -> dict[str, Any]:
    enrollment = (
        StudyEnrollment.objects.filter(user=request.user, is_active=True)
        .select_related("academic_year", "grade", "section")
        .first()
    )
    if not enrollment:
        raise PackUnavailable("NO_ENROLLMENT")
    unit = (
        Unit.objects.filter(id=unit_id, status=ContentStatus.PUBLISHED)
        .select_related("subject", "term")
        .first()
    )
    if not unit:
        raise PackUnavailable("PACK_NOT_FOUND")
    context = AccessContext.build(request.user, enrollment)
    return _build_unit_manifest(
        request=request, unit=unit, enrollment=enrollment, context=context,
    )


def build_subject_download_plan(*, request, subject_id: str) -> dict[str, Any]:
    enrollment = (
        StudyEnrollment.objects.filter(user=request.user, is_active=True)
        .select_related("academic_year", "grade", "section")
        .first()
    )
    subject = Subject.objects.filter(
        id=subject_id, status=ContentStatus.PUBLISHED,
    ).first()
    if not enrollment or not subject:
        raise PackUnavailable("PACK_NOT_FOUND")
    context = AccessContext.build(request.user, enrollment)
    units = []
    unit_queryset = subject.units.filter(
        status=ContentStatus.PUBLISHED,
    ).select_related("subject", "term").order_by("sort_order", "id")
    for unit in unit_queryset:
        decision = evaluate_access_with_context(
            context, "unit", unit.id, _known_unit_access_data(unit),
        )
        if decision.allowed:
            manifest = _build_unit_manifest(
                request=request,
                unit=unit,
                enrollment=enrollment,
                context=context,
                decision=decision,
            )
            units.append({
                "unit_id": str(unit.id),
                "title": unit.title,
                "total_bytes": manifest["total_bytes"],
                "content_version": manifest["content_version"],
                "manifest_url": request.build_absolute_uri(reverse(
                    "downloads:unit-manifest", kwargs={"unit_id": unit.id},
                )),
            })
    return {
        "subject_id": str(subject.id),
        "subject_title": subject.name_ar,
        "unit_packs": units,
        "total_bytes": sum(item["total_bytes"] for item in units),
    }


def current_unit_payload(*, request, unit_id: str, expected_checksum: str) -> bytes:
    manifest = build_unit_manifest(request=request, unit_id=unit_id)
    payload_resource = manifest["resources"][0]
    if not expected_checksum or expected_checksum != payload_resource["checksum"]:
        raise PackUnavailable("PACK_VERSION_CHANGED")
    unit = Unit.objects.select_related("subject").get(id=unit_id)
    return _canonical_bytes(_unit_payload(unit))
