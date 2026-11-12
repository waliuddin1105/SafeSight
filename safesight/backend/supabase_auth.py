"""Supabase Auth HTTP boundary; tokens stay in server-side application storage."""

from __future__ import annotations

import json
import urllib.error
import urllib.request


class AuthRejected(Exception):
    """Supabase rejected credentials or a session token."""


class AuthUnavailable(Exception):
    """Supabase Auth could not complete a request."""


class SupabaseAuth:
    """Use the documented Auth API with a publishable key, never an admin key."""

    def __init__(self, url: str, key: str):
        self.url, self.key = url.rstrip("/"), key

    def request(self, path: str, data: dict | None = None, token: str | None = None) -> dict:
        """Return parsed JSON and sanitize provider/network errors."""
        headers = {"apikey": self.key, "Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        request = urllib.request.Request(
            self.url + "/auth/v1/" + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                body = response.read()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as error:
            if error.code in (400, 401, 403, 422):
                raise AuthRejected("Credentials or session rejected") from None
            raise AuthUnavailable("Authentication service unavailable or rate limited") from None
        except (OSError, ValueError):
            raise AuthUnavailable("Authentication service unavailable") from None

    def login(self, email: str, password: str) -> dict:
        return self.request("token?grant_type=password", {"email": email, "password": password})

    def refresh(self, refresh_token: str) -> dict:
        return self.request("token?grant_type=refresh_token", {"refresh_token": refresh_token})

    def user(self, token: str) -> dict:
        return self.request("user", token=token)

    def logout(self, token: str) -> None:
        self.request("logout?scope=local", {}, token)
