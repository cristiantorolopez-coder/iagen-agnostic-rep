from rest_framework import serializers


class ChatRequestSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=2000)
    session_id = serializers.CharField(max_length=64, required=False, default="default")


class ChatResponseSerializer(serializers.Serializer):
    answer = serializers.CharField()
    source = serializers.CharField()
    session_id = serializers.CharField()


class DatabricksLoadRequestSerializer(serializers.Serializer):
    query = serializers.CharField(
        max_length=4000,
        help_text="SQL query to execute on the Databricks warehouse.",
    )
    table_name = serializers.CharField(
        max_length=128,
        help_text="Name to register the resulting DataFrame under in the pipeline.",
    )
    server_hostname = serializers.CharField(
        max_length=256,
        required=False,
        allow_blank=True,
        default="",
        help_text="Overrides DATABRICKS_HOST env var.",
    )
    http_path = serializers.CharField(
        max_length=256,
        required=False,
        allow_blank=True,
        default="",
        help_text="Overrides DATABRICKS_HTTP_PATH env var.",
    )


class DatabricksLoadResponseSerializer(serializers.Serializer):
    table_name = serializers.CharField()
    rows = serializers.IntegerField()
    columns = serializers.ListField(child=serializers.CharField())
