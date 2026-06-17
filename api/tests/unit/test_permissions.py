"""Testes unitários da regra de permissão de edição/exclusão de projeto.

_assert_can_edit: admin OU criador podem; terceiro recebe 403.
"""
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.projects import _assert_can_edit
from app.domain.sample.entities import Project
from app.domain.shared.value_objects import MarkerType, ProjectCode


def _project(created_by):
    return Project(
        code=ProjectCode("PROJ"),
        name="Projeto",
        marker_type=MarkerType.S16,
        created_by=created_by,
    )


def test_admin_can_edit_any_project():
    project = _project(created_by=uuid4())
    # admin diferente do criador
    _assert_can_edit(project, {"user_id": str(uuid4()), "role": "admin"})


def test_owner_can_edit_own_project():
    owner = uuid4()
    project = _project(created_by=owner)
    _assert_can_edit(project, {"user_id": str(owner), "role": "researcher"})


def test_other_researcher_forbidden():
    project = _project(created_by=uuid4())
    with pytest.raises(HTTPException) as exc:
        _assert_can_edit(project, {"user_id": str(uuid4()), "role": "researcher"})
    assert exc.value.status_code == 403


def test_no_creator_and_not_admin_forbidden():
    project = _project(created_by=None)
    with pytest.raises(HTTPException) as exc:
        _assert_can_edit(project, {"user_id": str(uuid4()), "role": "researcher"})
    assert exc.value.status_code == 403
