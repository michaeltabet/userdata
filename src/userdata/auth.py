# Copyright 2026 Michael Tabet
# SPDX-License-Identifier: MIT
"""Checks the authentik access tokens Claude sends."""

import jwt
from mcp.server.auth import provider

SCOPE = "userdata"


class AuthentikVerifier:
    """Accepts authentik access tokens issued for USERDATA."""

    def __init__(self, issuer: str, audience: str) -> None:
        """Prepares the verifier; keys are fetched on first use and cached."""
        self.issuer = issuer
        self.audience = audience
        self._keys = jwt.PyJWKClient(f"{issuer}jwks/", cache_keys=True)

    async def verify_token(self, token: str) -> provider.AccessToken | None:
        """Returns the token's access info, or None if it is not valid."""
        try:
            key = self._keys.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
            )
        except jwt.PyJWTError:
            return None
        scopes = claims.get("scope", "").split()
        if SCOPE not in scopes:
            return None
        return provider.AccessToken(
            token=token,
            client_id=self.audience,
            scopes=scopes,
            expires_at=claims["exp"],
            subject=claims["sub"],
        )
