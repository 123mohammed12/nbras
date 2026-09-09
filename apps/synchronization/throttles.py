from rest_framework.throttling import SimpleRateThrottle


class SyncManifestMinuteRateThrottle(SimpleRateThrottle):
    scope = "sync_manifest_minute"

    def get_cache_key(self, request, view):
        if not request.user or not request.user.is_authenticated:
            ident = self.get_ident(request)
        else:
            ident = str(request.user.pk)
        installation_id = request.headers.get("X-Installation-Id") or request.query_params.get("installation_id") or "default"
        return self.cache_format % {
            "scope": self.scope,
            "ident": f"{ident}:{installation_id}",
        }


class SyncManifestHourRateThrottle(SimpleRateThrottle):
    scope = "sync_manifest_hour"

    def get_cache_key(self, request, view):
        if not request.user or not request.user.is_authenticated:
            ident = self.get_ident(request)
        else:
            ident = str(request.user.pk)
        installation_id = request.headers.get("X-Installation-Id") or request.query_params.get("installation_id") or "default"
        return self.cache_format % {
            "scope": self.scope,
            "ident": f"{ident}:{installation_id}",
        }


class SyncOperationsMinuteRateThrottle(SimpleRateThrottle):
    scope = "sync_operations_minute"

    def get_cache_key(self, request, view):
        if not request.user or not request.user.is_authenticated:
            ident = self.get_ident(request)
        else:
            ident = str(request.user.pk)
        installation_id = request.headers.get("X-Installation-Id") or request.data.get("installation_id") or "default"
        return self.cache_format % {
            "scope": self.scope,
            "ident": f"{ident}:{installation_id}",
        }


class SyncOperationsHourRateThrottle(SimpleRateThrottle):
    scope = "sync_operations_hour"

    def get_cache_key(self, request, view):
        if not request.user or not request.user.is_authenticated:
            ident = self.get_ident(request)
        else:
            ident = str(request.user.pk)
        installation_id = request.headers.get("X-Installation-Id") or request.data.get("installation_id") or "default"
        return self.cache_format % {
            "scope": self.scope,
            "ident": f"{ident}:{installation_id}",
        }
