from django.urls import path
from . import api

urlpatterns = [
    path("", api.InboxView.as_view()),
    path("unread-count/", api.UnreadCountView.as_view()),
    path("read-all/", api.ReadAllView.as_view()),
    path("preferences/", api.PreferencesView.as_view()),
    path("devices/", api.DeviceView.as_view()),
    path("<uuid:pk>/", api.DetailView.as_view()),
    path("<uuid:pk>/read/", api.ReadView.as_view()),
]
