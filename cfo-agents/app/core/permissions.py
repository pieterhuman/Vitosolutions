"""Role-based permission checks."""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    OWNER = "owner"      # full power, can change settings + approve
    APPROVER = "approver"  # can approve/reject recommendations
    VIEWER = "viewer"    # read-only


class Permission(str, Enum):
    READ_RECOMMENDATIONS = "read:recommendations"
    APPROVE_RECOMMENDATIONS = "approve:recommendations"
    POST_TO_XERO = "post:xero"
    EDIT_SETTINGS = "edit:settings"
    SYNC = "trigger:sync"


ROLE_GRANTS: dict[Role, set[Permission]] = {
    Role.OWNER: {
        Permission.READ_RECOMMENDATIONS,
        Permission.APPROVE_RECOMMENDATIONS,
        Permission.POST_TO_XERO,
        Permission.EDIT_SETTINGS,
        Permission.SYNC,
    },
    Role.APPROVER: {
        Permission.READ_RECOMMENDATIONS,
        Permission.APPROVE_RECOMMENDATIONS,
        Permission.POST_TO_XERO,
        Permission.SYNC,
    },
    Role.VIEWER: {Permission.READ_RECOMMENDATIONS},
}


def has_permission(role: Role | str, permission: Permission) -> bool:
    if isinstance(role, str):
        role = Role(role)
    return permission in ROLE_GRANTS.get(role, set())


class PermissionDenied(Exception):
    pass


def require(role: Role | str, permission: Permission) -> None:
    if not has_permission(role, permission):
        raise PermissionDenied(f"{role} lacks {permission}")
