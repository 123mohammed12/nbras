from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field, OpenApiTypes
from apps.attempts.models import AssessmentAttempt, AttemptQuestion, AttemptAnswer, AttemptAnalysis
from apps.attempts.services.grading import grade_attempt_answer


class AttemptQuestionSerializer(serializers.ModelSerializer):
    question_text = serializers.SerializerMethodField()
    prompt_layout = serializers.SerializerMethodField()
    question_type = serializers.SerializerMethodField()
    options = serializers.SerializerMethodField()
    stimuli = serializers.SerializerMethodField()
    assets = serializers.SerializerMethodField()
    model_answer = serializers.SerializerMethodField()
    year = serializers.SerializerMethodField()
    exam_role = serializers.SerializerMethodField()
    model_number = serializers.SerializerMethodField()
    saved_answer = serializers.SerializerMethodField()
    answered = serializers.SerializerMethodField()
    is_flagged = serializers.SerializerMethodField()
    is_visited = serializers.SerializerMethodField()
    is_evaluated = serializers.SerializerMethodField()
    feedback = serializers.SerializerMethodField()
    source_metadata = serializers.SerializerMethodField()
    answer_revision = serializers.SerializerMethodField()
    client_revision = serializers.SerializerMethodField()

    class Meta:
        model = AttemptQuestion
        fields = [
            "id",
            "sort_order",
            "points",
            "question_type",
            "question_text",
            "prompt_layout",
            "options",
            "stimuli",
            "assets",
            "is_reference",
            "model_answer",
            "year",
            "exam_role",
            "model_number",
            "saved_answer",
            "answered",
            "is_flagged",
            "is_visited",
            "is_evaluated",
            "feedback",
            "source_type",
            "source_metadata",
            "answer_revision",
            "client_revision",
        ]

    def get_source_metadata(self, obj):
        return obj.source_metadata_snapshot or {}

    def get_answer_revision(self, obj):
        answer = self._answer(obj)
        return answer.server_revision if answer else 0

    def get_client_revision(self, obj):
        answer = self._answer(obj)
        return answer.client_revision if answer else 0

    def _answer(self, obj):
        ans_map = getattr(self.context.get("view"), "_answers_map", None) if self.context else None
        if ans_map is not None:
            return ans_map.get(obj.id)
        return AttemptAnswer.objects.filter(attempt_question=obj).first()

    @extend_schema_field(OpenApiTypes.STR)
    def get_question_text(self, obj):
        if obj.question_snapshot and "question_text" in obj.question_snapshot:
            return obj.question_snapshot["question_text"]
        return getattr(obj.question_version, "question_text", "")

    @extend_schema_field(OpenApiTypes.STR)
    def get_prompt_layout(self, obj):
        if obj.question_snapshot and "prompt_layout" in obj.question_snapshot:
            return obj.question_snapshot["prompt_layout"]
        return getattr(obj.question_version, "prompt_layout", "vertical")

    @extend_schema_field(OpenApiTypes.STR)
    def get_question_type(self, obj):
        if obj.question_snapshot and "question_type" in obj.question_snapshot:
            return obj.question_snapshot["question_type"]
        return getattr(getattr(obj.question_version, "question", None), "question_type", "multiple_choice")

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_options(self, obj):
        if obj.question_snapshot and "options" in obj.question_snapshot:
            opts = obj.question_snapshot["options"]
            clean_opts = []
            for opt in opts:
                clean_opts.append({
                    "id": opt.get("id"),
                    "option_key": opt.get("option_key"),
                    "option_text": opt.get("option_text"),
                    "option_image_path": opt.get("option_image_path"),
                    "sort_order": opt.get("sort_order"),
                })
            return clean_opts
        return []

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_stimuli(self, obj):
        if obj.question_snapshot and "stimuli" in obj.question_snapshot:
            return obj.question_snapshot["stimuli"]
        return []

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_assets(self, obj):
        return (obj.question_snapshot or {}).get("assets", [])

    @extend_schema_field(OpenApiTypes.STR)
    def get_model_answer(self, obj):
        if not obj.is_reference:
            return None
        attempt = obj.attempt
        terminal = attempt.status in {
            "submitted", "evaluated", "pending_review", "expired"
        }
        if attempt.feedback_policy == "deferred" and not terminal:
            return None
        return (obj.question_snapshot or {}).get("model_answer")

    @extend_schema_field(OpenApiTypes.INT)
    def get_year(self, obj):
        return obj.source_metadata_snapshot.get("year")

    @extend_schema_field(OpenApiTypes.STR)
    def get_exam_role(self, obj):
        return obj.source_metadata_snapshot.get("exam_role")

    @extend_schema_field(OpenApiTypes.STR)
    def get_model_number(self, obj):
        return obj.source_metadata_snapshot.get("model_number")

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_saved_answer(self, obj):
        ans = self._answer(obj)
        if not ans:
            return None
        return ans.answer_payload or {
            "selected_option_id": str(ans.selected_option_id) if ans.selected_option_id else None,
            "selected_option_key": ans.selected_option_key,
            "text": ans.answer_text,
        }

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_answered(self, obj):
        ans = self._answer(obj)
        return ans is not None and bool(ans.selected_option_id or ans.answer_text or ans.answer_payload)

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_flagged(self, obj):
        ans = self._answer(obj)
        return ans.is_flagged if ans else False

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_visited(self, obj):
        ans = self._answer(obj)
        return ans.is_visited if ans else False

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_evaluated(self, obj):
        ans = self._answer(obj)
        return bool(ans and ans.is_evaluated)

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_feedback(self, obj):
        ans = self._answer(obj)
        if not ans or not ans.is_evaluated or obj.attempt.feedback_policy != "immediate":
            return None
        result = grade_attempt_answer(
            question_snapshot=obj.question_snapshot,
            answer_payload=ans.answer_payload or {},
            max_points=obj.points,
        )
        return {
            "is_correct": result["is_correct"],
            "awarded_points": float(ans.awarded_points),
            "max_points": float(obj.points),
            "feedback_state": result["feedback_state"],
            "correct_option_key": result["correct_option_key"],
            "explanation": result["explanation"],
        }


class AssessmentAttemptSerializer(serializers.ModelSerializer):
    access = serializers.SerializerMethodField()
    assessment_title = serializers.SerializerMethodField()
    assessment_type = serializers.SerializerMethodField()
    time_remaining_seconds = serializers.SerializerMethodField()
    total_questions = serializers.IntegerField(source="attempt_questions.count", read_only=True)
    server_time = serializers.SerializerMethodField()

    class Meta:
        model = AssessmentAttempt
        fields = [
            "access",
            "id",
            "assessment_id",
            "assessment_title",
            "assessment_type",
            "attempt_type",
            "mode",
            "status",
            "display_mode",
            "contract_version",
            "revision",
            "source_scope",
            "feedback_policy",
            "timing_mode",
            "started_at",
            "submitted_at",
            "expires_at",
            "time_remaining_seconds",
            "server_time",
            "answered_count",
            "correct_count",
            "incorrect_count",
            "unanswered_count",
            "pending_review_count",
            "score",
            "maximum_score",
            "official_maximum_score",
            "percentage",
            "total_questions",
        ]

    def get_assessment_title(self, obj):
        return obj.assessment_title

    def get_access(self, obj):
        from apps.entitlements.services.access_service import check_attempt_snapshot_access
        request = self.context.get("request")
        return check_attempt_snapshot_access(
            user=request.user if request else obj.user, attempt=obj,
        ).to_dict()

    def get_assessment_type(self, obj):
        return obj.assessment_kind

    @extend_schema_field(OpenApiTypes.INT)
    def get_time_remaining_seconds(self, obj):
        if not obj.expires_at:
            return None
        from django.utils import timezone
        delta = (obj.expires_at - timezone.now()).total_seconds()
        return max(0, int(delta))

    def get_server_time(self, obj):
        from django.utils import timezone
        return timezone.now().isoformat()


class AttemptStartRequestSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=["practice", "exam"], default="exam")
    shuffle_questions = serializers.BooleanField(required=False, default=None)
    shuffle_options = serializers.BooleanField(required=False, default=None)
    client_attempt_id = serializers.UUIDField(required=False, default=None)


class AssessmentSourceStartRequestSerializer(serializers.Serializer):
    idempotency_key = serializers.CharField(required=False, allow_blank=False)
    year = serializers.IntegerField(required=False, min_value=1900, max_value=2200)
    batch = serializers.IntegerField(required=False, min_value=1)
    exam_id = serializers.UUIDField(required=False)
    part = serializers.IntegerField(required=False, min_value=1)


class AttemptSaveAnswerRequestSerializer(serializers.Serializer):
    attempt_question_id = serializers.UUIDField()
    answer = serializers.DictField(required=False, default=dict)
    selected_option_id = serializers.UUIDField(required=False, default=None)
    selected_option_key = serializers.CharField(required=False, allow_blank=False, default=None)
    answer_text = serializers.CharField(required=False, allow_blank=True, default="")
    is_flagged = serializers.BooleanField(required=False, default=False)
    response_time_seconds = serializers.IntegerField(required=False, default=0)
    client_revision = serializers.IntegerField(required=False, default=0, min_value=0)
    expected_revision = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    expected_answer_revision = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    client_mutation_id = serializers.CharField(required=False, allow_blank=False, max_length=128)
    is_visited = serializers.BooleanField(required=False, default=True)
    evaluate = serializers.BooleanField(required=False, default=False)


class AttemptSubmitRequestSerializer(serializers.Serializer):
    answers = serializers.ListField(child=serializers.DictField(), required=False, default=list)
    submission_reason = serializers.ChoiceField(
        choices=["manual", "time_expired"], required=False, default="manual"
    )
    expected_revision = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    client_mutation_id = serializers.CharField(required=False, allow_blank=False, max_length=128)
    final_frozen_at = serializers.DateTimeField(required=False, allow_null=True)


class PracticeAnswerResponseSerializer(serializers.Serializer):
    saved = serializers.BooleanField()
    answered = serializers.BooleanField()
    mode = serializers.CharField()
    is_correct = serializers.BooleanField(allow_null=True)
    awarded_points = serializers.FloatField()
    max_points = serializers.FloatField()
    feedback_state = serializers.CharField()
    selected_option_id = serializers.CharField(allow_null=True)
    selected_option_ids = serializers.ListField(child=serializers.CharField())
    selected_option_key = serializers.CharField(allow_null=True, required=False)
    selected_option_keys = serializers.ListField(child=serializers.CharField(), required=False)
    correct_option_id = serializers.CharField(allow_null=True)
    correct_option_ids = serializers.ListField(child=serializers.CharField())
    correct_option_key = serializers.CharField(allow_null=True, required=False)
    correct_option_keys = serializers.ListField(child=serializers.CharField(), required=False)
    correct_answer = serializers.CharField(allow_null=True)
    explanation = serializers.CharField(allow_blank=True)
    time_remaining_seconds = serializers.IntegerField(allow_null=True)
    answer_revision = serializers.IntegerField()
    attempt_revision = serializers.IntegerField()
    server_time = serializers.DateTimeField()
    idempotent_replay = serializers.BooleanField()


class ExamAnswerResponseSerializer(serializers.Serializer):
    saved = serializers.BooleanField()
    answered = serializers.BooleanField()
    mode = serializers.CharField()
    answered_count = serializers.IntegerField()
    total_questions = serializers.IntegerField()
    time_remaining_seconds = serializers.IntegerField(allow_null=True)
    answer_revision = serializers.IntegerField()
    attempt_revision = serializers.IntegerField()
    server_time = serializers.DateTimeField()
    idempotent_replay = serializers.BooleanField()


class AttemptAnalysisSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttemptAnalysis
        fields = [
            "unit_breakdown",
            "lesson_breakdown",
            "difficulty_breakdown",
            "year_breakdown",
            "strengths",
            "weaknesses",
            "recommendations",
        ]


class AttemptResultSerializer(serializers.ModelSerializer):
    assessment_title = serializers.SerializerMethodField()
    assessment_type = serializers.SerializerMethodField()
    analysis = AttemptAnalysisSerializer(read_only=True)
    gradable_maximum_score = serializers.DecimalField(
        source="maximum_score", max_digits=6, decimal_places=2, read_only=True
    )
    gradable_count = serializers.SerializerMethodField()
    reference_count = serializers.SerializerMethodField()
    allowed_actions = serializers.SerializerMethodField()

    class Meta:
        model = AssessmentAttempt
        fields = [
            "id",
            "assessment_id",
            "assessment_title",
            "assessment_type",
            "attempt_type",
            "mode",
            "status",
            "revision",
            "score",
            "maximum_score",
            "gradable_maximum_score",
            "official_maximum_score",
            "percentage",
            "answered_count",
            "correct_count",
            "incorrect_count",
            "unanswered_count",
            "gradable_count",
            "reference_count",
            "pending_review_count",
            "started_at",
            "submitted_at",
            "duration_seconds",
            "submission_reason",
            "allowed_actions",
            "analysis",
        ]

    def get_assessment_title(self, obj):
        return obj.assessment_title

    def get_assessment_type(self, obj):
        return obj.assessment_kind

    def get_gradable_count(self, obj):
        return obj.attempt_questions.filter(is_reference=False).count()

    def get_reference_count(self, obj):
        return obj.attempt_questions.filter(is_reference=True).count()

    def get_allowed_actions(self, obj):
        from apps.attempts.services.ar06_practice import (
            _eligible_wrong_questions,
            preferred_weakness_for_attempt,
        )

        finalized = obj.status in {"submitted", "evaluated", "pending_review", "expired"}
        wrong_count = len(_eligible_wrong_questions(obj)) if finalized else 0
        weakness = preferred_weakness_for_attempt(user=obj.user, attempt=obj) if finalized else None
        return {
            "can_review": finalized,
            "can_retry": finalized,
            "can_practice_wrong_answers": wrong_count > 0,
            "wrong_answers_count": wrong_count,
            "can_practice_weakness": weakness is not None,
            "weakness_signal": weakness,
            "can_create_new_with_same_settings": bool(
                obj.dynamic_assessment_type in {"custom_test", "mock_exam"}
                and finalized
            ),
        }


class CustomScopeSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=["subject", "units", "lessons"])
    unit_ids = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    lesson_ids = serializers.ListField(child=serializers.CharField(), required=False, default=list)


class CustomSourcePercentagesSerializer(serializers.Serializer):
    ministerial = serializers.IntegerField(min_value=0, max_value=100)
    training = serializers.IntegerField(min_value=0, max_value=100)


class CustomTestSpecSerializer(serializers.Serializer):
    subject_id = serializers.CharField()
    scope = CustomScopeSerializer()
    sources = serializers.ListField(child=serializers.ChoiceField(choices=["ministerial", "training"]))
    years = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)
    difficulties = serializers.ListField(child=serializers.ChoiceField(choices=["easy", "medium", "hard"]), required=False, default=list)
    question_types = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    count = serializers.IntegerField(min_value=1)
    mode = serializers.ChoiceField(choices=["practice", "exam"])
    duration_minutes = serializers.IntegerField(required=False, allow_null=True)
    source_percentages = CustomSourcePercentagesSerializer(required=False, allow_null=True)
    exclude_previously_answered = serializers.BooleanField(required=False, default=False)


class CustomTestCreateSerializer(CustomTestSpecSerializer):
    allow_available = serializers.BooleanField(required=False, default=False)
    idempotency_key = serializers.CharField(required=False, allow_blank=False)


class CustomTestNewSameSettingsSerializer(serializers.Serializer):
    idempotency_key = serializers.CharField(required=False, allow_blank=False)


class MockStartSerializer(serializers.Serializer):
    idempotency_key = serializers.CharField(required=False, allow_blank=False)


class PracticeScopeSerializer(serializers.Serializer):
    subject_id = serializers.CharField()
    unit_id = serializers.CharField(required=False, allow_null=True, allow_blank=False)
    lesson_id = serializers.CharField(required=False, allow_null=True, allow_blank=False)


class WrongPracticeCreateSerializer(PracticeScopeSerializer):
    count = serializers.IntegerField(required=False, default=15, min_value=1, max_value=20)


class WeaknessPracticeCreateSerializer(PracticeScopeSerializer):
    dimension = serializers.ChoiceField(
        choices=["subject", "unit", "lesson", "difficulty", "question_type", "source"]
    )
    value = serializers.CharField()
    source = serializers.ChoiceField(
        choices=["training", "ministerial"], required=False, default="training",
    )
    count = serializers.IntegerField(required=False, default=10, min_value=1, max_value=20)
