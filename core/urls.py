from django.contrib.auth.views import LogoutView
from django.urls import path

from .views import auth, help_requests, library, passport, queue, training, upload, workspace

urlpatterns = [
    path("", auth.home, name="home"),
    path("login/", auth.Login.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("queue/", queue.queue, name="queue"),
    path("claims/new/", workspace.claim_new, name="claim_new"),
    path("claims/<int:pk>/", workspace.claim, name="claim"),
    path("claims/<int:pk>/export/", workspace.claim_export, name="claim_export"),
    path("claims/<int:pk>/review/", workspace.claim_review, name="claim_review"),
    path("claims/<int:pk>/answer/<int:index>/", workspace.claim_answer, name="claim_answer"),
    path("help/", help_requests.help_list, name="help_list"),
    path("help/<int:pk>/", help_requests.help_detail, name="help_detail"),
    path("library/", library.library, name="library"),
    path("library/<int:pk>/", library.library_detail, name="library_detail"),
    path("library/<int:pk>/edit/", library.library_edit, name="library_edit"),
    path("library/<int:pk>/delete/", library.library_delete, name="library_delete"),
    path("passport/", passport.passport, name="passport"),
    path("passport/<str:username>/", passport.passport, name="passport_user"),
    path("training/", training.training, name="training"),
    path("training/<int:pk>/", training.training_exercise, name="training_exercise"),
    path("upload/", upload.upload, name="upload"),
    path("upload/template/", upload.upload_template, name="upload_template"),
]
