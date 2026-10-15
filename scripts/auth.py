"""Keycloak access-token verification. No client secret or user credentials required."""
from dataclasses import dataclass
import os
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from jwt.exceptions import InvalidTokenError, PyJWKClientConnectionError, PyJWKClientError, PyJWKSetError

APP_ROLES = frozenset({"agent_admin", "agent_manager", "agent_user"})
bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthSettings:
    issuer: str
    jwks_url: str
    audience: str

    @classmethod
    def from_env(cls):
        issuer = os.environ.get("KEYCLOAK_ISSUER", "http://10.8.6.32:18080/realms/company-dev").rstrip("/")
        return cls(issuer, os.environ.get("KEYCLOAK_JWKS_URL", f"{issuer}/protocol/openid-connect/certs"),
                   os.environ.get("KEYCLOAK_AUDIENCE", "marketing-workflow-automation-api"))


def unauthorized():
    return HTTPException(401, "登录已失效，请重新登录。", headers={"WWW-Authenticate": "Bearer"})


class TokenVerifier:
    def __init__(self, settings=None, jwks_client=None):
        self.settings = settings or AuthSettings.from_env()
        self.jwks = jwks_client or PyJWKClient(self.settings.jwks_url, timeout=5, lifespan=300)

    def verify(self, token: str) -> dict:
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str) or not header["kid"]:
                raise unauthorized()
            key = self.jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["RS256"], audience=self.settings.audience,
                                issuer=self.settings.issuer,
                                options={"require": ["exp", "iat", "iss", "aud", "sub"]})
        except (PyJWKClientConnectionError, PyJWKSetError):
            raise HTTPException(503, "统一认证服务暂时不可用，请稍后重试。") from None
        except (InvalidTokenError, PyJWKClientError, ValueError, TypeError):
            raise unauthorized() from None

        # Keycloak ID tokens must never be accepted as API access tokens.
        if claims.get("typ") != "Bearer" or not isinstance(claims.get("sub"), str) or not claims["sub"].strip():
            raise unauthorized()
        resources = claims.get("resource_access")
        resource = resources.get(self.settings.audience) if isinstance(resources, dict) else None
        roles = resource.get("roles") if isinstance(resource, dict) else None
        if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
            roles = []
        granted = sorted(APP_ROLES.intersection(roles))
        if not granted:
            raise HTTPException(403, "当前账号没有流程自动审批访问权限，请联系管理员分配应用角色。")
        user = {"user_id": claims["sub"], "roles": granted}
        for field, claim in (("username", "preferred_username"), ("display_name", "name"),
                             ("email", "email"), ("department_code", "department_code"),
                             ("department_name", "department_name")):
            user[field] = claims.get(claim) if isinstance(claims.get(claim), str) else ""
        return user


def require_user(request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized()
    return request.app.state.token_verifier.verify(credentials.credentials)
