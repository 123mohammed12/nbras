import hmac
import hashlib
from rest_framework.throttling import SimpleRateThrottle
from django.conf import settings


class RedeemBurstRateThrottle(SimpleRateThrottle):
    scope = "activation_redeem_burst"

    def get_cache_key(self, request, view):
        if not request.user or not request.user.is_authenticated:
            ident = self.get_ident(request)
        else:
            ident = str(request.user.id)

        installation_id = request.META.get("HTTP_X_INSTALLATION_ID", "")
        code_input = request.data.get("code", "") if hasattr(request, "data") else ""

        code_hash = ""
        if code_input:
            secret = getattr(settings, "ACTIVATION_CODE_HMAC_SECRET", "DEV-SECRET")
            code_hash = hmac.new(secret.encode("utf-8"), str(code_input).strip().upper().encode("utf-8"), hashlib.sha256).hexdigest()[:16]

        return self.cache_format % {
            "scope": self.scope,
            "ident": f"{ident}:{installation_id}:{code_hash}",
        }


class RedeemSustainedRateThrottle(SimpleRateThrottle):
    scope = "activation_redeem_sustained"

    def get_cache_key(self, request, view):
        if not request.user or not request.user.is_authenticated:
            ident = self.get_ident(request)
        else:
            ident = str(request.user.id)

        installation_id = request.META.get("HTTP_X_INSTALLATION_ID", "")
        return self.cache_format % {
            "scope": self.scope,
            "ident": f"{ident}:{installation_id}",
        }
