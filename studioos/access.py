"""Per-project access (v0.6.3).

Admin, manager and accounts roles work across the whole firm and see every
project. Every other role (architect, site engineer, viewer) sees only the
projects the Admin has assigned them to. Enforced in the backend for every
read and write that names a project, including what the AI is shown.
"""
from __future__ import annotations
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import ProjectMember, Project

ALL_PROJECT_ROLES = ('admin', 'manager', 'accounts')


def sees_all_projects(user) -> bool:
    return getattr(user, 'role', None) in ALL_PROJECT_ROLES


def visible_project_ids(db: Session, user) -> set[int] | None:
    """None means every project; otherwise the set of assigned project ids."""
    if sees_all_projects(user):
        return None
    return set(db.scalars(select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)).all())


def can_access_project(db: Session, user, project_id) -> bool:
    if project_id is None:
        return sees_all_projects(user)
    allowed = visible_project_ids(db, user)
    return allowed is None or int(project_id) in allowed


def require_project_access(db: Session, user, project_id) -> None:
    if not can_access_project(db, user, project_id):
        # 404, not 403: do not confirm that a project you cannot see exists.
        raise HTTPException(404, 'Project not found')


def filter_projects(projects: list[dict], allowed: set[int] | None) -> list[dict]:
    return projects if allowed is None else [p for p in projects if p['id'] in allowed]


def project_names_for(db: Session, user) -> set[str]:
    allowed = visible_project_ids(db, user)
    rows = db.scalars(select(Project).where(Project.deleted_at.is_(None))).all()
    return {p.name.casefold() for p in rows if allowed is None or p.id in allowed}
