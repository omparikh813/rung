from django.contrib.auth.views import LogoutView
from django.urls import path

from .views import auth, queue

urlpatterns = [
    path("", auth.home, name="home"),
    path("login/", auth.Login.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("queue/", queue.queue, name="queue"),
]
