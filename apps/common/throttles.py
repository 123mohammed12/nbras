"""
Custom throttle classes for rate limiting.
"""

from rest_framework.throttling import SimpleRateThrottle


class OTPRequestThrottle(SimpleRateThrottle):
    """Throttle OTP request attempts per phone number."""
    scope = "otp_request"

    def get_cache_key(self, request, view):
        phone = request.data.get("phone", "")
        ident = phone or self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class OTPVerifyThrottle(SimpleRateThrottle):
    """Throttle OTP verification attempts."""
    scope = "otp_verify"

    def get_cache_key(self, request, view):
        phone = request.data.get("phone", "")
        ident = phone or self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class GuestCreateThrottle(SimpleRateThrottle):
    """Throttle guest account creation per IP."""
    scope = "guest_create"

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }
