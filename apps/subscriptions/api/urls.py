from django.urls import path
from apps.subscriptions.api.views import (
    SubscriptionPlanListAPIView,
    MySubscriptionAPIView,
    MySubscriptionsListAPIView,
    RedeemActivationCodeAPIView,
    CheckResourceAccessAPIView,
    PreviewActivationCodeAPIView,
    SubscriptionCatalogAPIView,
)

app_name = "subscriptions"

urlpatterns = [
    path("subscriptions/plans/", SubscriptionPlanListAPIView.as_view(), name="plan-list"),
    path("subscriptions/catalog/", SubscriptionCatalogAPIView.as_view(), name="catalog"),
    path("me/subscription/", MySubscriptionAPIView.as_view(), name="my-subscription"),
    path("me/subscriptions/", MySubscriptionsListAPIView.as_view(), name="my-subscriptions-list"),
    path("activation-codes/redeem/", RedeemActivationCodeAPIView.as_view(), name="redeem-code"),
    path("activation-codes/preview/", PreviewActivationCodeAPIView.as_view(), name="preview-code"),
    path("access/check/", CheckResourceAccessAPIView.as_view(), name="check-access"),
]
