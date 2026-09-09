from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse

from apps.common.api import success_response, error_response
from apps.common.exceptions import ApplicationError
from apps.common.idempotency import idempotent_view
from apps.common.pagination import StandardPagination
from apps.content.selectors.content_selectors import (
    get_published_summaries,
    get_published_reader_summary,
    get_published_flashcard_decks,
    get_published_deck_cards,
    get_published_content_links,
    get_published_lesson_explanation,
)
from apps.curriculum.models import StudyEnrollment
from apps.entitlements.services.access_service import check_resource_access
from apps.entitlements.services.access_service import check_resources_access_batch


def _protected_list_data(request, objects, serializer_class, resource_type, private_fields):
    objects = list(objects)
    decisions = check_resources_access_batch(user=request.user, resources=[
        {"type": resource_type, "id": str(obj.pk)} for obj in objects
    ])
    rows = serializer_class(objects, many=True, context={"request": request}).data
    for obj, row in zip(objects, rows):
        decision = decisions[(resource_type, str(obj.pk))]
        row["access"] = decision.to_dict()
        if not decision.allowed:
            for field in private_fields:
                row[field] = None
            row["is_downloadable"] = False
    return rows


def _content_denial(request, resource_type, resource_id):
    decision = check_resource_access(user=request.user, resource_type=resource_type, resource_id=str(resource_id))
    if not decision.allowed:
        return error_response(decision.reason_code, "هذا المحتوى غير متاح ضمن وصولك الحالي.", status=403)
    return None
from apps.progress.models import LearningResourceProgress
from apps.content.api.serializers import (
    SummarySerializer,
    FlashcardDeckSerializer,
    FlashcardSerializer,
    ContentLinkSerializer,
    LessonExplanationSerializer,
    SmartCardSessionStartRequestSerializer,
    SmartCardReviewRequestSerializer,
    SmartCardSessionSerializer,
    SmartCardSessionStateSerializer,
    SmartCardReviewSerializer,
)
from apps.content.services.smart_card_sessions import (
    ALLOWED_REVIEW_ACTIONS,
    rating_counts_for,
    review_smart_card,
    start_or_resume_smart_card_session,
)


class SummaryListAPIView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SummarySerializer

    @extend_schema(
        summary="قائمة ملخصات الدروس والوحدات",
        description="عرض الملخصات النصية والملفات التابعة لدرس أو وحدة أو مادة بشرط النشر.",
        parameters=[
            OpenApiParameter(name="subject_id", type=str, location=OpenApiParameter.QUERY, description="فلترة بحسب المادة"),
            OpenApiParameter(name="unit_id", type=str, location=OpenApiParameter.QUERY, description="فلترة بحسب الوحدة"),
            OpenApiParameter(name="lesson_id", type=str, location=OpenApiParameter.QUERY, description="فلترة بحسب الدرس"),
        ],
        responses={200: SummarySerializer(many=True)},
    )
    def get(self, request):
        subject_id = request.query_params.get("subject_id")
        unit_id = request.query_params.get("unit_id")
        lesson_id = request.query_params.get("lesson_id")

        qs = get_published_summaries(
            subject_id=subject_id,
            unit_id=unit_id,
            lesson_id=lesson_id,
        )

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            data = _protected_list_data(request, page, self.serializer_class, "summary", ("body", "download_url"))
            return paginator.get_paginated_response(data)

        data = _protected_list_data(request, qs, self.serializer_class, "summary", ("body", "download_url"))
        return success_response(data=data)


class SummaryDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SummarySerializer

    @extend_schema(
        summary="تفاصيل مورد ملخص للقارئ",
        responses={
            200: SummarySerializer,
            403: OpenApiResponse(description="لا يملك المستخدم صلاحية المورد"),
            404: OpenApiResponse(description="المورد غير موجود أو غير منشور"),
        },
    )
    def get(self, request, pk):
        summary = get_published_reader_summary(str(pk))
        if summary is None:
            return error_response(
                "SUMMARY_NOT_FOUND",
                "الملخص غير موجود أو غير منشور.",
                status=404,
            )

        enrollment = (
            StudyEnrollment.objects.filter(user=request.user, is_active=True)
            .select_related("grade", "section")
            .first()
        )
        decision = check_resource_access(
            user=request.user,
            enrollment=enrollment,
            resource_type="summary",
            resource_id=str(summary.id),
        )
        if not decision.allowed:
            return error_response(
                decision.reason_code,
                "ليس لديك صلاحية للوصول إلى هذا الملخص.",
                status=403,
            )

        progress = None
        if enrollment is not None:
            progress = LearningResourceProgress.objects.filter(
                user=request.user,
                study_enrollment=enrollment,
                resource_type="summary",
                resource_id=str(summary.id),
            ).first()

        data = dict(
            self.serializer_class(summary, context={"request": request}).data
        )
        data["access"] = decision.to_dict()
        current_version = str(summary.version)
        snapshot = progress.resource_snapshot if progress else {}
        position_version_matches = bool(
            progress and progress.source_version == current_version
        )
        data["reading_progress"] = {
            "status": progress.status if progress else "not_started",
            "progress_percentage": (
                float(progress.completion_percentage) if progress else 0.0
            ),
            "last_position": (
                float(snapshot.get("last_position", 0.0))
                if position_version_matches
                else 0.0
            ),
            "started_at": progress.started_at if progress else None,
            "last_opened_at": progress.last_activity_at if progress else None,
            "completed_at": progress.completed_at if progress else None,
            "source_version": current_version,
        }
        return success_response(data=data)


class FlashcardDeckListAPIView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = FlashcardDeckSerializer

    @extend_schema(
        summary="قائمة حزم البطاقات التعليمية",
        description="جلب حزم البطاقات التعليمية المتاحة والمنشورة.",
        parameters=[
            OpenApiParameter(name="subject_id", type=str, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="unit_id", type=str, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="lesson_id", type=str, location=OpenApiParameter.QUERY),
        ],
        responses={200: FlashcardDeckSerializer(many=True)},
    )
    def get(self, request):
        subject_id = request.query_params.get("subject_id")
        unit_id = request.query_params.get("unit_id")
        lesson_id = request.query_params.get("lesson_id")

        qs = get_published_flashcard_decks(
            subject_id=subject_id,
            unit_id=unit_id,
            lesson_id=lesson_id,
        )

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            serializer = self.serializer_class(page, many=True, context={"request": request})
            return paginator.get_paginated_response(serializer.data)

        serializer = self.serializer_class(qs, many=True, context={"request": request})
        return success_response(data=serializer.data)


class FlashcardDeckCardsAPIView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = FlashcardSerializer

    @extend_schema(
        summary="بطاقات حزمة معينة",
        description="جلب البطاقات التعليمية النشطة التابعة لحزمة محددة.",
        parameters=[
            OpenApiParameter(name="pk", type=str, location=OpenApiParameter.PATH, description="معرف الحزمة UUID"),
        ],
        responses={200: FlashcardSerializer(many=True)},
    )
    def get(self, request, pk):
        denial = _content_denial(request, "flashcard_deck", pk)
        if denial is not None:
            return denial
        cards = get_published_deck_cards(deck_id=str(pk))

        paginator = StandardPagination()
        page = paginator.paginate_queryset(cards, request, view=self)
        if page is not None:
            serializer = self.serializer_class(page, many=True, context={"request": request})
            return paginator.get_paginated_response(serializer.data)

        serializer = self.serializer_class(cards, many=True, context={"request": request})
        return success_response(data=serializer.data)


def _session_state(session):
    counts = rating_counts_for(session)
    reviewed_count = sum(counts.values())
    return {
        "session_id": session.id,
        "client_session_id": session.client_session_id,
        "source_type": "deck",
        "source_id": session.resource_id,
        "status": session.status,
        "total_cards": session.total_items,
        "current_position": session.current_position,
        "reviewed_count": reviewed_count,
        "remaining_count": max(session.total_items - reviewed_count, 0),
        "rating_counts": {
            "again": counts.get("again", 0),
            "hard": counts.get("hard", 0),
            "good": counts.get("good", 0),
        },
        "completed_at": session.ended_at,
    }


class SmartCardSessionStartAPIView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SmartCardSessionStartRequestSerializer

    @extend_schema(
        summary="بدء أو متابعة جلسة بطاقات ذكية",
        request=SmartCardSessionStartRequestSerializer,
        responses={200: SmartCardSessionSerializer},
    )
    @idempotent_view
    def post(self, request, pk):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            session, deck, cards, decision = start_or_resume_smart_card_session(
                user=request.user,
                deck_id=str(pk),
                client_session_id=serializer.validated_data["client_session_id"],
            )
        except ApplicationError as exc:
            return error_response(exc.code, exc.message, status=exc.status_code)

        data = {
            **_session_state(session),
            "deck": {
                "deck_id": str(deck.id),
                "title": deck.title,
                "description": deck.description,
                "subject_id": str(deck.subject_id) if deck.subject_id else None,
                "unit_id": str(deck.unit_id) if deck.unit_id else None,
                "lesson_id": str(deck.lesson_id) if deck.lesson_id else None,
            },
            "cards": FlashcardSerializer(
                cards, many=True, context={"request": request}
            ).data,
            "allowed_review_actions": ALLOWED_REVIEW_ACTIONS,
            "access": decision.to_dict(),
        }
        return success_response(data=SmartCardSessionSerializer(data).data)


class SmartCardSessionReviewAPIView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SmartCardReviewRequestSerializer

    @extend_schema(
        summary="تسجيل تقييم بطاقة داخل الجلسة",
        request=SmartCardReviewRequestSerializer,
    )
    @idempotent_view
    def post(self, request, session_id):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            session, review, replayed = review_smart_card(
                user=request.user,
                session_id=str(session_id),
                card_id=str(serializer.validated_data["card_id"]),
                rating=serializer.validated_data["rating"],
                client_event_id=serializer.validated_data["client_event_id"],
                reviewed_at=serializer.validated_data.get("reviewed_at"),
            )
        except ApplicationError as exc:
            return error_response(exc.code, exc.message, status=exc.status_code)

        review_data = SmartCardReviewSerializer(
            {
                "card_id": review.card_id,
                "rating": review.rating,
                "client_event_id": review.client_event_id,
                "reviewed_at": review.reviewed_at,
            }
        ).data
        return success_response(
            data={
                "review": review_data,
                "session": SmartCardSessionStateSerializer(
                    _session_state(session)
                ).data,
                "replayed": replayed,
            }
        )


class ContentLinkListAPIView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ContentLinkSerializer

    @extend_schema(
        summary="روابط الوسائط والمحتوى الملحق",
        description="جلب روابط الفيديو والمقالات والملفات الملحقة المنشورة.",
        parameters=[
            OpenApiParameter(name="subject_id", type=str, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="unit_id", type=str, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="lesson_id", type=str, location=OpenApiParameter.QUERY),
        ],
        responses={200: ContentLinkSerializer(many=True)},
    )
    def get(self, request):
        subject_id = request.query_params.get("subject_id")
        unit_id = request.query_params.get("unit_id")
        lesson_id = request.query_params.get("lesson_id")

        qs = get_published_content_links(
            subject_id=subject_id,
            unit_id=unit_id,
            lesson_id=lesson_id,
        )

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            data = _protected_list_data(request, page, self.serializer_class, "content_link", ("url", "attached_file_url", "thumbnail_url"))
            return paginator.get_paginated_response(data)

        data = _protected_list_data(request, qs, self.serializer_class, "content_link", ("url", "attached_file_url", "thumbnail_url"))
        return success_response(data=data)


class LessonExplanationDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LessonExplanationSerializer

    @extend_schema(
        summary="شرح الدرس النصي",
        description="جلب الشرح التفصيلي للدرس (بأنواع plain_text أو markdown).",
        parameters=[
            OpenApiParameter(name="lesson_id", type=str, location=OpenApiParameter.PATH, description="معرف الدرس UUID"),
        ],
        responses={
            200: LessonExplanationSerializer,
            404: OpenApiResponse(description="الشرح غير موجود أو غير منشور"),
        },
    )
    def get(self, request, lesson_id):
        denial = _content_denial(request, "lesson", lesson_id)
        if denial is not None:
            return denial
        explanation = get_published_lesson_explanation(lesson_id=str(lesson_id))
        if not explanation:
            return error_response(
                "EXPLANATION_NOT_FOUND",
                "شرح الدرس غير موجود أو غير منشور.",
                status=404,
            )


        serializer = self.serializer_class(explanation, context={"request": request})
        return success_response(data=serializer.data)
