"""JSON API of the accounts domain (roles): thin endpoints over the use cases in `shared`.

Every endpoint parses the request (flat JSON / path params), calls the use case with flat
parameters and translates the result into JSON (data -> DTO, `Failure` -> `abort(status)`). Zero
queries and zero `commit` here. The ORM session is opened by the blog's app-wide
`before_app_request` hook into `g.session`.

**The blueprint here is `accounts-api` and the pages next door are `accounts`.** Two
blueprints cannot share a `url_for` name, and this one held the plain one for as long as the
domain had no pages to collide with it — the same story `inventory`, `billing` and `taxonomy` each
went through. The convention they settled is applied here: a plain name is the pages, the `-api`
suffix is the JSON.
"""

from __future__ import annotations

from flask import abort, g, jsonify, request
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from apps import wire
from apps.accounts import usecases
from shared.dto.accounts_dto import role_dict
from shared.usecases.result import FAILURE_STATUS

accounts = Blueprint(
    "accounts-api",
    __name__,
    url_prefix="/api/accounts",
    description="Accounts: roles and assignments",
)


@accounts.get("/roles")
def list_roles() -> ResponseReturnValue:
    """Every role in the system."""
    return jsonify([role_dict(r) for r in usecases.list_roles(g.session)])


@accounts.get("/users/<int:user_id>/roles")
def roles_of_user(user_id: int) -> ResponseReturnValue:
    """The roles of a user (through the UserRole bridge table)."""
    return jsonify([role_dict(r) for r in usecases.roles_of_user(g.session, user_id)])


@accounts.post("/roles")
def create_role() -> ResponseReturnValue:
    """Create a role. 400 if the name comes in empty."""
    payload = wire.json_object(request)
    result = usecases.create_role(g.session, wire.text(payload.get("name")))
    if isinstance(result, usecases.Failure):
        abort(FAILURE_STATUS[result.reason])
    return jsonify(role_dict(result)), 201


@accounts.post("/users/<int:user_id>/roles")
def assign_role(user_id: int) -> ResponseReturnValue:
    """Assign a role to a user. 404 if the role does not exist."""
    payload = wire.json_object(request)
    role_id = wire.integer(payload.get("role_id"))
    result = usecases.assign_role(g.session, user_id, role_id)
    if isinstance(result, usecases.Failure):
        abort(FAILURE_STATUS[result.reason])
    return jsonify({"user_id": user_id, "role_id": role_id}), 201


@accounts.delete("/users/<int:user_id>/roles/<int:role_id>")
def revoke_role(user_id: int, role_id: int) -> ResponseReturnValue:
    """Take a role away from a user. 404 if that assignment did not exist."""
    result = usecases.revoke_role(g.session, user_id, role_id)
    if isinstance(result, usecases.Failure):
        abort(FAILURE_STATUS[result.reason])
    return "", 204
