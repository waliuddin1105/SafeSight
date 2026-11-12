"""Explicit fake Supabase boundary for deterministic offline software tests."""

from safesight.backend.supabase_auth import AuthRejected

SUBJECT = "00000000-0000-0000-0000-000000000123"
EMAIL = "admin@example.test"


class FakeAuth:
    """No JWT validity or live Supabase service is implied by this fixture."""

    revoked = False
    unavailable = False
    refreshes = 0

    def login(self, email, password):
        if email != EMAIL or password != "test-password-123":
            raise AuthRejected()
        self.revoked = False
        return {"access_token": "fixture-access", "refresh_token": "fixture-refresh", "expires_in": 3600}

    def user(self, token):
        from safesight.backend.supabase_auth import AuthUnavailable

        if self.unavailable:
            raise AuthUnavailable()
        if self.revoked or token not in ("fixture-access", "fixture-refreshed"):
            raise AuthRejected()
        return {"id": SUBJECT, "email": EMAIL}

    def refresh(self, token):
        if self.revoked or token != "fixture-refresh":
            raise AuthRejected()
        self.refreshes += 1
        return {"access_token": "fixture-refreshed", "refresh_token": "fixture-refresh", "expires_in": 3600}

    def logout(self, token):
        self.revoked = True
