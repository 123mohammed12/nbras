from rest_framework import serializers


class SubjectCenterHeaderSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    icon_path = serializers.CharField(allow_null=True)
    cover_image_path = serializers.CharField(allow_null=True)
    grade_name = serializers.CharField()
    section_name = serializers.CharField(allow_null=True)


class SubjectCenterProgressSerializer(serializers.Serializer):
    status = serializers.CharField()
    completion_percentage = serializers.FloatField()
    lessons_completed = serializers.IntegerField()
    lessons_total = serializers.IntegerField()


class SubjectCenterUnitSerializer(serializers.Serializer):
    id = serializers.CharField()
    number = serializers.IntegerField()
    title = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    sort_order = serializers.IntegerField()
    published_lessons_count = serializers.IntegerField()
    unit_tests_count = serializers.IntegerField()
    summaries_count = serializers.IntegerField()
    smart_cards_count = serializers.IntegerField()
    access_status = serializers.ChoiceField(
        choices=("available", "free", "subscribed", "locked")
    )
    access = serializers.DictField(allow_null=True)
    progress = SubjectCenterProgressSerializer(allow_null=True)


class SubjectCenterAttemptSerializer(serializers.Serializer):
    id = serializers.CharField()
    status = serializers.CharField()
    score = serializers.FloatField()
    maximum_score = serializers.FloatField()
    percentage = serializers.FloatField()


class SubjectCenterExamSerializer(serializers.Serializer):
    id = serializers.CharField()
    assessment_id = serializers.CharField(allow_null=True)
    title = serializers.CharField()
    model_number = serializers.CharField()
    year = serializers.IntegerField()
    exam_role = serializers.CharField(allow_null=True)
    total_questions = serializers.IntegerField()
    total_points = serializers.FloatField(allow_null=True)
    duration_minutes = serializers.IntegerField(allow_null=True)
    can_start = serializers.BooleanField()
    free_access_rank = serializers.IntegerField(allow_null=True)
    access = serializers.DictField(allow_null=True)
    incomplete_attempt = SubjectCenterAttemptSerializer(allow_null=True)
    latest_attempt = SubjectCenterAttemptSerializer(allow_null=True)
    best_attempt = SubjectCenterAttemptSerializer(allow_null=True)


class SubjectCenterSummarySerializer(serializers.Serializer):
    id = serializers.CharField()
    title = serializers.CharField()
    summary_type = serializers.CharField()
    unit_id = serializers.CharField(allow_null=True)
    unit_title = serializers.CharField(allow_null=True)
    lesson_id = serializers.CharField(allow_null=True)
    lesson_title = serializers.CharField(allow_null=True)


class UnitStatisticSerializer(serializers.Serializer):
    unit_id = serializers.CharField()
    unit_title = serializers.CharField()
    completion_percentage = serializers.FloatField()


class RankedLessonSerializer(serializers.Serializer):
    lesson_id = serializers.CharField()
    lesson_title = serializers.CharField()
    completion_percentage = serializers.FloatField()


class RankedExamSerializer(serializers.Serializer):
    exam_id = serializers.CharField()
    exam_title = serializers.CharField()
    percentage = serializers.FloatField()


class SubjectCenterStatisticsSerializer(serializers.Serializer):
    has_activity = serializers.BooleanField()
    overall_completion_percentage = serializers.FloatField(allow_null=True)
    units_completed = serializers.IntegerField()
    units_total = serializers.IntegerField()
    lessons_completed = serializers.IntegerField()
    lessons_total = serializers.IntegerField()
    attempted_exams_count = serializers.IntegerField()
    average_score = serializers.FloatField(allow_null=True)
    unit_progress = UnitStatisticSerializer(many=True)
    top_lessons = RankedLessonSerializer(many=True)
    best_exams = RankedExamSerializer(many=True)


class SubjectTrainingCardSerializer(serializers.Serializer):
    assessment_id = serializers.CharField(allow_null=True, required=False)
    source_kind = serializers.CharField()
    source_id = serializers.CharField()
    assessment_type = serializers.CharField()
    title = serializers.CharField()
    questions_count = serializers.IntegerField()
    session_question_count = serializers.IntegerField()
    total_pool_question_count = serializers.IntegerField()
    covered_questions_count = serializers.IntegerField()
    batch_index = serializers.IntegerField()
    batch_count = serializers.IntegerField()
    duration = serializers.IntegerField(allow_null=True)
    attempt_status = serializers.CharField()
    unfinished_attempt_id = serializers.CharField(allow_null=True)
    last_score = serializers.FloatField(allow_null=True)
    best_score = serializers.FloatField(allow_null=True)
    is_available = serializers.BooleanField()
    access = serializers.DictField()
    free_access_rank = serializers.IntegerField(allow_null=True)
    display_state = serializers.CharField()
    last_activity_at = serializers.DateTimeField(allow_null=True)


class SubjectTrainingSerializer(serializers.Serializer):
    access = serializers.DictField()
    tests = SubjectTrainingCardSerializer(many=True)
    total_questions_count = serializers.IntegerField()
    covered_questions_count = serializers.IntegerField()
    batch_count = serializers.IntegerField()
    has_more = serializers.BooleanField()


class SubjectCenterSerializer(serializers.Serializer):
    subject = SubjectCenterHeaderSerializer()
    units = SubjectCenterUnitSerializer(many=True)
    exam_years = serializers.ListField(child=serializers.IntegerField())
    ministerial_exams = SubjectCenterExamSerializer(many=True)
    summaries = SubjectCenterSummarySerializer(many=True)
    training = SubjectTrainingSerializer()
    statistics = SubjectCenterStatisticsSerializer()


class SubjectCenterResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    data = SubjectCenterSerializer()
