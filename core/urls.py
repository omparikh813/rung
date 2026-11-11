from django.contrib.auth.views import LogoutView
from django.urls import path

from .views import auth, queue, workspace

urlpatterns = [
    path("", auth.home, name="home"),
    path("login/", auth.Login.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("queue/", queue.queue, name="queue"),
    path("claims/<int:pk>/", workspace.claim, name="claim"),
    path("claims/<int:pk>/review/", workspace.claim_review, name="claim_review"),
    path("claims/<int:pk>/answer/<int:index>/", workspace.claim_answer, name="claim_answer"),
]
