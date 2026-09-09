"""
Session Serializers.
"""

from rest_framework import serializers
from apps.accounts.models import UserSession
from apps.accounts.serializers.device_serializers import UserDeviceSerializer


class UserSessionSerializer(serializers.ModelSerializer):
    device = UserDeviceSerializer(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    is_current_device = serializers.SerializerMethodField()

    class Meta:
        model = UserSession
        fields = [
            "id",
            "device",
            "created_at",
            "last_used_at",
            "expires_at",
            "revoked_at",
            "is_active",
            "is_current_device",
        ]
        read_only_fields = fields

    def get_is_current_device(self, obj) -> bool:
        installation_id = self.context.get("installation_id")
        return bool(obj.device and installation_id and obj.device.installation_id == installation_id)
