"""Router of the accounts domain (roles): a thin JSON API over the use cases in `shared`.

Every endpoint parses the request (Pydantic), calls the use case with flat parameters and translates
the result into JSON (data -> DTO, `Failure` -> HTTPException). Zero queries, zero `commit` here.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from apps.accounts import usecases
from apps.accounts.usecases import Failure
from apps.deps import SessionDep, http_error
from shared.dto.accounts_dto import role_dict

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


class RoleIn(BaseModel):
    """Body for creating a role."""

    name: str


class AssignIn(BaseModel):
    """Body for assigning a role to a user."""

    role_id: int


@router.get("/roles")
async def list_roles(session: SessionDep) -> list[dict[str, object]]:
    """Every role in the system."""
    return [role_dict(r) for r in await usecases.list_roles(session)]


@router.get("/users/{user_id}/roles")
async def roles_of_user(user_id: int, session: SessionDep) -> list[dict[str, object]]:
    """The roles of a user (through the UserRole bridge table)."""
    return [role_dict(r) for r in await usecases.roles_of_user(session, user_id)]


@router.post("/roles", status_code=201)
async def create_role(payload: RoleIn, session: SessionDep) -> dict[str, object]:
    """Create a role. 400 if the name comes in empty."""
    result = await usecases.create_role(session, payload.name)
    if isinstance(result, Failure):
        raise http_error(result)
    return role_dict(result)


@router.post("/users/{user_id}/roles", status_code=201)
async def assign_role(
    user_id: int, payload: AssignIn, session: SessionDep
) -> dict[str, object]:
    """Assign a role to a user. 404 if the role does not exist."""
    result = await usecases.assign_role(session, user_id, payload.role_id)
    if isinstance(result, Failure):
        raise http_error(result)
    return {"user_id": user_id, "role_id": payload.role_id}


@router.delete("/users/{user_id}/roles/{role_id}", status_code=204)
async def revoke_role(user_id: int, role_id: int, session: SessionDep) -> None:
    """Take a role away from a user. 404 if that assignment did not exist."""
    result = await usecases.revoke_role(session, user_id, role_id)
    if isinstance(result, Failure):
        raise http_error(result)
