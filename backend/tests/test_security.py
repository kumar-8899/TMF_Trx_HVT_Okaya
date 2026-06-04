"""Core authz: Principal/wildcard + the require_permission/require_role deps."""

import pytest
from fastapi import Depends, FastAPI
from starlette.testclient import TestClient

from core.services.auth_verify import AuthError, Principal, TokenVerifier, permission_granted
from core.services.security import require_permission, require_role


# --- permission matching ---------------------------------------------------


@pytest.mark.parametrize(
    "held,needed,ok",
    [
        ({"AUTH.MANAGE_USERS"}, "AUTH.MANAGE_USERS", True),
        ({"AUTH.*"}, "AUTH.MANAGE_USERS", True),
        ({"*"}, "TEST.RUN", True),
        ({"TEST.RUN"}, "AUTH.MANAGE_USERS", False),
        ({"AUTH.*"}, "TEST.RUN", False),
        (set(), "TEST.RUN", False),
    ],
)
def test_permission_granted(held, needed, ok):
    assert permission_granted(frozenset(held), needed) is ok


def test_principal_has_permission():
    p = Principal("alice", role="engineer", permissions=frozenset({"TEST.RUN", "RECIPE.*"}))
    assert p.has_permission("TEST.RUN")
    assert p.has_permission("RECIPE.EDIT")
    assert not p.has_permission("AUTH.MANAGE_USERS")


# --- TokenVerifier token-level checks --------------------------------------


def _verifier():
    tv = TokenVerifier()
    table = {
        "admin": Principal("admin", role="admin", permissions=frozenset({"AUTH.*"})),
        "op": Principal("op", role="operator", permissions=frozenset({"TEST.RUN"})),
        "super": Principal("root", role="super_admin", permissions=frozenset({"*"})),
    }

    def verify(token):
        if token not in table:
            raise AuthError("bad token")
        return table[token]

    tv.register(verify)
    return tv


def test_token_require_permission_and_role():
    tv = _verifier()
    assert tv.require_permission("admin", "AUTH.MANAGE_USERS").subject == "admin"
    with pytest.raises(AuthError):
        tv.require_permission("op", "AUTH.MANAGE_USERS")
    assert tv.require_role("admin", "admin").role == "admin"
    with pytest.raises(AuthError):
        tv.require_role("op", "admin")


# --- FastAPI dependencies --------------------------------------------------


def _app():
    app = FastAPI()
    app.state.auth = _verifier()

    @app.get("/need-users", dependencies=[Depends(require_permission("AUTH.MANAGE_USERS"))])
    async def need_users():
        return {"ok": True}

    @app.get("/need-admin", dependencies=[Depends(require_role("admin"))])
    async def need_admin():
        return {"ok": True}

    return TestClient(app)


def test_dep_401_without_token():
    assert _app().get("/need-users").status_code == 401


def test_dep_401_bad_token():
    assert _app().get("/need-users", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_dep_403_lacks_permission():
    c = _app()
    assert c.get("/need-users", headers={"Authorization": "Bearer op"}).status_code == 403


def test_dep_200_with_permission_wildcard():
    c = _app()
    # admin holds AUTH.* -> grants AUTH.MANAGE_USERS
    assert c.get("/need-users", headers={"Authorization": "Bearer admin"}).status_code == 200
    # super holds * -> grants anything
    assert c.get("/need-users", headers={"Authorization": "Bearer super"}).status_code == 200


def test_role_dep():
    c = _app()
    assert c.get("/need-admin", headers={"Authorization": "Bearer admin"}).status_code == 200
    assert c.get("/need-admin", headers={"Authorization": "Bearer op"}).status_code == 403
