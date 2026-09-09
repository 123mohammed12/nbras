from rest_framework import serializers


class LessonCenterLessonSerializer(serializers.Serializer):
    lesson_id = serializers.CharField()
    unit_id = serializers.CharField()
    subject_id = serializers.CharField()
    title = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    sort_order = serializers.IntegerField()
    lesson_number = serializers.IntegerField()
    status = serializers.CharField()
    subject_name = serializers.CharField()
    unit_name = serializers.CharField()
    subject_icon_path = serializers.CharField(allow_null=True)


class LessonCenterAccessSerializer(serializers.Serializer):
    allowed = serializers.BooleanField()
    reason_code = serializers.CharField()
    requires_subscription = serializers.BooleanField(required=False)
    is_free = serializers.BooleanField(required=False)


class LessonCenterProgressSerializer(serializers.Serializer):
    completion_percentage = serializers.FloatField()
    completion_status = serializers.CharField()
    started_at = serializers.DateTimeField(allow_null=True, required=False)
    completed_at = serializers.DateTimeField(allow_null=True, required=False)
    last_activity_at = serializers.DateTimeField(allow_null=True, required=False)


class LessonResumeTargetSerializer(serializers.Serializer):
    type = serializers.CharField()
    resource_id = serializers.CharField()
    section = serializers.CharField()
    progress = serializers.FloatField(required=False, allow_null=True)


class LessonContentMetadataSerializer(serializers.Serializer):
    content_id = serializers.CharField()
    title = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    content_type = serializers.CharField()
    sort_order = serializers.IntegerField()
    estimated_duration = serializers.IntegerField(allow_null=True, required=False)
    has_images = serializers.BooleanField(default=False)
    has_attachments = serializers.BooleanField(default=False)
    progress = serializers.FloatField(default=0.0)
    status = serializers.CharField()
    is_available = serializers.BooleanField(default=True)


class LessonSummarySerializer(serializers.Serializer):
    id = serializers.CharField()
    title = serializers.CharField()
    description = serializers.CharField(allow_blank=True, required=False, allow_null=True)
    summary_type = serializers.CharField()
    lesson_id = serializers.CharField(allow_null=True)
    lesson_title = serializers.CharField(allow_null=True)
    sort_order = serializers.IntegerField(default=0)
    progress_percentage = serializers.FloatField(allow_null=True)
    can_open = serializers.BooleanField()


class LessonSmartCardDeckSerializer(serializers.Serializer):
    id = serializers.CharField()
    title = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    lesson_id = serializers.CharField(allow_null=True)
    lesson_title = serializers.CharField(allow_null=True)
    sort_order = serializers.IntegerField(default=0)
    cards_count = serializers.IntegerField()
    reviewed_count = serializers.IntegerField(default=0)
    due_count = serializers.IntegerField(default=0)
    review_status = serializers.CharField()
    progress_percentage = serializers.FloatField(allow_null=True)
    is_available = serializers.BooleanField()


class LessonMinisterialGroupSerializer(serializers.Serializer):
    exam_id = serializers.CharField()
    title = serializers.CharField()
    year = serializers.IntegerField()
    model_number = serializers.CharField()
    exam_role = serializers.CharField(allow_null=True)
    questions_count = serializers.IntegerField()
    sort_order = serializers.IntegerField(default=0)
    is_available = serializers.BooleanField()


class LessonTrainingTestSerializer(serializers.Serializer):
    assessment_id = serializers.CharField(required=False, allow_null=True)
    source_kind = serializers.CharField(required=False)
    source_id = serializers.CharField(required=False)
    assessment_type = serializers.CharField()
    title = serializers.CharField()
    questions_count = serializers.IntegerField()
    total_pool_question_count = serializers.IntegerField(required=False)
    covered_questions_count = serializers.IntegerField(required=False, default=0)
    session_question_count = serializers.IntegerField(required=False, allow_null=True)
    batch_index = serializers.IntegerField(required=False, allow_null=True)
    batch_count = serializers.IntegerField(required=False, allow_null=True)
    duration = serializers.IntegerField(allow_null=True)
    attempt_status = serializers.CharField()
    unfinished_attempt_id = serializers.CharField(allow_null=True)
    last_score = serializers.FloatField(allow_null=True)
    best_score = serializers.FloatField(allow_null=True)
    is_available = serializers.BooleanField()
    display_state = serializers.CharField(required=False)
    last_activity_at = serializers.DateTimeField(required=False, allow_null=True)


class LessonTestCategorySerializer(serializers.Serializer):
    category = serializers.CharField()
    label = serializers.CharField()
    years = serializers.ListField(child=serializers.IntegerField(), required=False)
    groups = LessonMinisterialGroupSerializer(many=True, required=False)
    tests = LessonTrainingTestSerializer(many=True, required=False)


class LessonCenterSerializer(serializers.Serializer):
    lesson = LessonCenterLessonSerializer()
    access = LessonCenterAccessSerializer()
    progress = LessonCenterProgressSerializer()
    resume_target = LessonResumeTargetSerializer(allow_null=True)
    content = LessonContentMetadataSerializer(allow_null=True)
    summaries = LessonSummarySerializer(many=True)
    smart_card_decks = LessonSmartCardDeckSerializer(many=True)
    tests = LessonTestCategorySerializer(many=True)


class LessonCenterResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    data = LessonCenterSerializer()
