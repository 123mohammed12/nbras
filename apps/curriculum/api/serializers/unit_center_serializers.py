from rest_framework import serializers


class UnitCenterUnitSerializer(serializers.Serializer):
    unit_id = serializers.CharField()
    subject_id = serializers.CharField()
    subject_name = serializers.CharField()
    subject_icon_path = serializers.CharField(allow_null=True)
    title = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    sort_order = serializers.IntegerField()
    number = serializers.IntegerField()
    lessons_count = serializers.IntegerField()
    is_free = serializers.BooleanField()


class UnitCenterAccessSerializer(serializers.Serializer):
    allowed = serializers.BooleanField()
    reason_code = serializers.CharField()
    source = serializers.CharField(allow_null=True, required=False)
    scope_type = serializers.CharField(allow_null=True, required=False)
    scope_id = serializers.CharField(allow_null=True, required=False)
    requires_subscription = serializers.BooleanField(required=False)
    upgrade_required = serializers.BooleanField(required=False)
    expires_at = serializers.DateTimeField(allow_null=True, required=False)


class UnitCenterProgressSerializer(serializers.Serializer):
    completion_percentage = serializers.FloatField()
    completed_lessons_count = serializers.IntegerField()
    lessons_count = serializers.IntegerField()
    average_score = serializers.FloatField(allow_null=True)
    last_activity = serializers.DateTimeField(allow_null=True)


class ResumeTargetSerializer(serializers.Serializer):
    lesson_id = serializers.CharField()
    lesson_title = serializers.CharField()
    is_first_lesson = serializers.BooleanField(required=False)


class UnitCenterLessonSerializer(serializers.Serializer):
    lesson_id = serializers.CharField()
    unit_id = serializers.CharField()
    title = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    sort_order = serializers.IntegerField()
    progress_percentage = serializers.FloatField()
    completion_status = serializers.CharField()
    ministerial_questions_count = serializers.IntegerField()
    has_summary = serializers.BooleanField()
    has_smart_cards = serializers.BooleanField()
    has_assessment = serializers.BooleanField()
    resume_target = serializers.DictField(allow_null=True)


class UnitMinisterialGroupSerializer(serializers.Serializer):
    source_kind = serializers.CharField()
    source_id = serializers.CharField()
    title = serializers.CharField()
    year = serializers.IntegerField()
    exam_id = serializers.UUIDField()
    exam_role = serializers.CharField(allow_null=True)
    model_number = serializers.CharField()
    questions_count = serializers.IntegerField()
    model_questions_count = serializers.IntegerField()
    part_index = serializers.IntegerField()
    part_count = serializers.IntegerField()
    is_available = serializers.BooleanField()


class UnitAssessmentSerializer(serializers.Serializer):
    assessment_id = serializers.CharField(allow_null=True, required=False)
    source_kind = serializers.CharField()
    source_id = serializers.CharField()
    title = serializers.CharField()
    questions_count = serializers.IntegerField()
    is_available = serializers.BooleanField()
    assessment_type = serializers.CharField(required=False)
    total_pool_question_count = serializers.IntegerField(required=False)
    covered_questions_count = serializers.IntegerField(required=False)
    session_question_count = serializers.IntegerField(required=False)
    batch_index = serializers.IntegerField(required=False, allow_null=True)
    batch_count = serializers.IntegerField(required=False, allow_null=True)
    duration = serializers.IntegerField(required=False, allow_null=True)
    attempt_status = serializers.CharField(required=False)
    unfinished_attempt_id = serializers.CharField(required=False, allow_null=True)
    last_score = serializers.FloatField(required=False, allow_null=True)
    best_score = serializers.FloatField(required=False, allow_null=True)
    display_state = serializers.CharField(required=False)
    last_activity_at = serializers.DateTimeField(required=False, allow_null=True)


class UnitTestCategorySerializer(serializers.Serializer):
    category = serializers.ChoiceField(choices=("ministerial", "training", "custom"))
    label = serializers.CharField()
    years = serializers.ListField(child=serializers.IntegerField())
    groups = UnitMinisterialGroupSerializer(many=True)
    assessments = UnitAssessmentSerializer(many=True, required=False)
    total_questions_count = serializers.IntegerField(required=False, default=0)
    covered_questions_count = serializers.IntegerField(required=False, default=0)


class UnitSummarySerializer(serializers.Serializer):
    id = serializers.CharField()
    title = serializers.CharField()
    description = serializers.CharField(allow_blank=True, required=False, allow_null=True)
    summary_type = serializers.CharField()
    lesson_id = serializers.CharField(allow_null=True)
    lesson_title = serializers.CharField(allow_null=True)
    sort_order = serializers.IntegerField(required=False, default=0)
    progress_percentage = serializers.FloatField(allow_null=True)
    can_open = serializers.BooleanField()


class UnitSmartCardDeckSerializer(serializers.Serializer):
    id = serializers.CharField()
    title = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    lesson_id = serializers.CharField(allow_null=True)
    lesson_title = serializers.CharField(allow_null=True)
    cards_count = serializers.IntegerField()
    reviewed_count = serializers.IntegerField(default=0)
    progress_percentage = serializers.FloatField(allow_null=True)
    review_status = serializers.CharField()
    can_open = serializers.BooleanField()


class UnitCenterSerializer(serializers.Serializer):
    unit = UnitCenterUnitSerializer()
    access = UnitCenterAccessSerializer()
    progress = UnitCenterProgressSerializer()
    resume_target = ResumeTargetSerializer(allow_null=True)
    lessons = UnitCenterLessonSerializer(many=True)
    tests = UnitTestCategorySerializer(many=True)
    summaries = UnitSummarySerializer(many=True)
    smart_card_decks = UnitSmartCardDeckSerializer(many=True)


class UnitCenterResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    data = UnitCenterSerializer()
