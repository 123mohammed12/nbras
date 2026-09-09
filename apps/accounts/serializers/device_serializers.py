"""
Device Serializers.
"""

from rest_framework import serializers

from apps.accounts.models import UserDevice


class UserDeviceSerializer(serializers.ModelSerializer):
    # Mask installation_id — show only last 4 chars
    installation_id = serializers.SerializerMethodField()

    class Meta:
        model = UserDevice
        fields = [
            "id",
            "installation_id",
            "platform",
            "device_name",
            "operating_system",
            "app_version",
            "first_seen_at",
            "last_seen_at",
            "is_active",
        ]
        read_only_fields = [
            "id",
            "installation_id",
            "first_seen_at",
            "last_seen_at",
        ]
        # push_token is explicitly excluded from API output

    def get_installation_id(self, obj) -> str:
        """Return masked installation_id — last 4 chars only."""
        iid = obj.installation_id or ""
        if len(iid) > 4:
            return f"***{iid[-4:]}"
        return iid
