from django.db.models import Sum, F
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema
from apps.common.api import success_response
from apps.analytics.models import StudentPerformanceInsight, DailyLearningSummary, AnalyticsEvent
from apps.analytics.api.serializers import StudentPerformanceInsightSerializer, BasicAnalyticsSerializer


class BasicAnalyticsAPIView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = BasicAnalyticsSerializer

    @extend_schema(responses={200: BasicAnalyticsSerializer})
    def get(self, request):
        enrollment = getattr(request, "study_enrollment", None)
        if not enrollment:
            from apps.curriculum.models import StudyEnrollment
            enrollment = StudyEnrollment.objects.filter(user=request.user, is_active=True).first()
            
        summaries = DailyLearningSummary.objects.filter(user=request.user, study_enrollment=enrollment)
        aggs = summaries.aggregate(
            total_seconds=Sum("learning_seconds"),
            total_resources=Sum("resources_completed"),
            total_attempts=Sum("attempts_submitted"),
            total_questions=Sum("questions_answered"),
            total_correct=Sum("correct_answers"),
        )
        
        t_sec = aggs.get("total_seconds") or 0
        t_res = aggs.get("total_resources") or 0
        t_att = aggs.get("total_attempts") or 0
        t_ques = aggs.get("total_questions") or 0
        t_corr = aggs.get("total_correct") or 0
        
        acc = (t_corr / t_ques * 100.0) if t_ques > 0 else 0.0
        
        recent = AnalyticsEvent.objects.filter(
            user=request.user, study_enrollment=enrollment
        ).order_by("-occurred_at")[:5].values("event_type", "occurred_at")
        
        data = {
            "total_learning_seconds": t_sec,
            "resources_completed": t_res,
            "attempts_submitted": t_att,
            "questions_answered": t_ques,
            "correct_answers": t_corr,
            "accuracy_percentage": acc,
            "recent_activity": list(recent),
            "subject_summaries": [] # Can be expanded with grouped queries if needed
        }
        
        serializer = self.get_serializer(data)
        return success_response(data=serializer.data)


class StrengthsAnalyticsAPIView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = StudentPerformanceInsightSerializer
    queryset = StudentPerformanceInsight.objects.none()

    @extend_schema(responses={200: StudentPerformanceInsightSerializer(many=True)})
    def get(self, request):
        insights = StudentPerformanceInsight.objects.filter(user=request.user, insight_type="strength").select_related("subject", "unit", "lesson")
        serializer = self.get_serializer(insights, many=True)
        return success_response(data=serializer.data)


class WeaknessesAnalyticsAPIView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = StudentPerformanceInsightSerializer
    queryset = StudentPerformanceInsight.objects.none()

    @extend_schema(responses={200: StudentPerformanceInsightSerializer(many=True)})
    def get(self, request):
        insights = StudentPerformanceInsight.objects.filter(user=request.user, insight_type="weakness").select_related("subject", "unit", "lesson")
        serializer = self.get_serializer(insights, many=True)
        return success_response(data=serializer.data)
