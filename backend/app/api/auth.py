from dataclasses import dataclass
from enum import Enum
from typing import Dict

from fastapi import Header, HTTPException, status, Depends


class UserRole(str, Enum):
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"


class Capability(str, Enum):
    COMPUTE_V0 = "compute_v0"
    COMPUTE_ECOLOGY = "compute_ecology"
    GENERATE_BRIEFS = "generate_briefs"
    COMPUTE_V1 = "compute_v1"
    COMPUTE_ANOMALIES = "compute_anomalies"
    COMPUTE_CORRELATIONS = "compute_correlations"


_TOKEN_ROLES: Dict[str, tuple[str, UserRole]] = {
    "admin-token": ("admin", UserRole.ADMIN),
    "analyst-token": ("analyst", UserRole.ANALYST),
    "viewer-token": ("viewer", UserRole.VIEWER),
}


_ROLE_CAPABILITIES: Dict[UserRole, set[Capability]] = {
    UserRole.ADMIN: {
        Capability.COMPUTE_V0,
        Capability.COMPUTE_ECOLOGY,
        Capability.GENERATE_BRIEFS,
        Capability.COMPUTE_V1,
        Capability.COMPUTE_ANOMALIES,
        Capability.COMPUTE_CORRELATIONS,
    },
    UserRole.ANALYST: {
        Capability.COMPUTE_V0,
        Capability.COMPUTE_ECOLOGY,
        Capability.GENERATE_BRIEFS,
        Capability.COMPUTE_V1,
        Capability.COMPUTE_ANOMALIES,
        Capability.COMPUTE_CORRELATIONS,
    },
    UserRole.VIEWER: set(),
}


@dataclass
class AuthenticatedUser:
    username: str
    role: UserRole


def _resolve_user_from_token(token: str) -> AuthenticatedUser:
    if token in _TOKEN_ROLES:
        username, role = _TOKEN_ROLES[token]
        return AuthenticatedUser(username=username, role=role)
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid auth token")


def get_current_user(authorization: str | None = Header(None)) -> AuthenticatedUser:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header required")
    try:
        scheme, token = authorization.split(" ", 1)
    except ValueError as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Authorization header") from exc
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")
    return _resolve_user_from_token(token)


def capabilities_for_user(user: AuthenticatedUser) -> Dict[str, Dict[str, str | bool | None]]:
    allowed_caps = _ROLE_CAPABILITIES.get(user.role, set())
    capabilities: Dict[str, Dict[str, str | bool | None]] = {}
    for capability in Capability:
        allowed = capability in allowed_caps
        capabilities[capability.value] = {
            "allowed": allowed,
            "reason": None if allowed else "Insufficient role for compute actions",
        }
    return capabilities


def require_capability(capability: Capability):
    def dependency(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
        caps = _ROLE_CAPABILITIES.get(user.role, set())
        if capability not in caps:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Capability {capability.value} is not permitted for role {user.role.value}",
            )
        return user

    return dependency
