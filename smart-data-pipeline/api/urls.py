from django.urls import path
from api.views import ChatView, DatabricksLoadView, HealthView

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("chat/", ChatView.as_view(), name="chat"),
    path("databricks/load/", DatabricksLoadView.as_view(), name="databricks-load"),
]
