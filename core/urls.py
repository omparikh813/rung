from django.contrib.auth.views import LogoutView
from django.urls import path

from .views import auth, help_requests, passport, queue, workspace

urlpatterns = [
    path("", auth.home, name="home"),
    path("login/", auth.Login.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("queue/", queue.queue, name="queue"),
    path("claims/<int:pk>/", workspace.claim, name="claim"),
    path("claims/<int:pk>/review/", workspace.claim_review, name="claim_review"),
    path("claims/<int:pk>/answer/<int:index>/", workspace.claim_answer, name="claim_answer"),
    path("help/", help_requests.help_list, name="help_list"),
    path("help/<int:pk>/", help_requests.help_detail, name="help_detail"),
    path("passport/", passport.passport, name="passport"),
    path("passport/<str:username>/", passport.passport, name="passport_user"),
]
