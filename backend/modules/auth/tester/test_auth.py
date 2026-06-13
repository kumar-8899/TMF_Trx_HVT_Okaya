"""auth standalone tester (CORE.md §6.2) — core + auth + real :memory: db. No broker."""

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from core.framework.contract import CoreServices
from core.services.auth_verify import AuthError, TokenVerifier
from core.services.db import Database
from core.services.diagnostics import Diagnostics
from modules.auth.policy import PolicyError
from modules.auth.users import LOCKED, PASSWORD_RESET_REQUIRED
from modules.auth.variants.default import LocalDbAuth

USERS = [
    {"username": "admin", "password": "admin123", "role": "super_admin"},
    {"username": "op", "password": "oppass12", "role": "operator"},
]


async def _build(authenticator="password", users=USERS):
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    core = CoreServices(
        db=db, auth=TokenVerifier(),
        diag=Diagnostics("st1", "0.0.0", sinks=[lambda e: None]), station="st1",
    )
    config = {
        "authenticator": authenticator,
        "session_ttl_min": 480,
        "password_policy": {"min_length": 8},
        "roles": {"super_admin": ["AUTH.*", "TEST.*"], "operator": ["TEST.RUN"]},
        "users": users,
    }
    module = LocalDbAuth.construct(core, config)
    await module.init()
    return module, core, db


@pytest.fixture
async def ctx():
    module, core, db = await _build()
    yield module, core, db
    await db.close()


# --- login / verify / permissions -----------------------------------------


async def test_login_resolves_permissions_and_fills_port(ctx):
    module, core, _ = ctx
    res = await module.login("admin", {"password": "admin123"})
    assert res["principal"]["role"] == "super_admin"
    assert "AUTH.*" in res["principal"]["permissions"]
    # the core.auth port now verifies the issued token
    principal = core.auth.verify(res["token"])
    assert principal.subject == "admin"
    assert principal.has_permission("AUTH.MANAGE_USERS")  # via AUTH.* wildcard
    assert principal.has_permission("TEST.RUN")


async def test_wrong_password_rejected(ctx):
    module, _, _ = ctx
    with pytest.raises(AuthError):
        await module.login("admin", {"password": "nope"})


async def test_unknown_user_rejected(ctx):
    module, _, _ = ctx
    with pytest.raises(AuthError):
        await module.login("ghost", {"password": "x"})


async def test_logout_revokes(ctx):
    module, core, _ = ctx
    res = await module.login("op", {"password": "oppass12"})
    await module.logout(res["token"])
    with pytest.raises(AuthError):
        core.auth.verify(res["token"])


async def test_single_active_session(ctx):
    module, core, _ = ctx
    first = await module.login("admin", {"password": "admin123"})
    second = await module.login("admin", {"password": "admin123"})
    with pytest.raises(AuthError):
        core.auth.verify(first["token"])          # prior revoked
    assert core.auth.verify(second["token"]).subject == "admin"


async def test_expired_session_rejected(ctx):
    module, core, _ = ctx
    res = await module.login("op", {"password": "oppass12"})
    module.sessions._sessions[res["token"]]["expires"] = 0  # force-expire
    with pytest.raises(AuthError):
        core.auth.verify(res["token"])


async def test_locked_user_cannot_login(ctx):
    module, _, _ = ctx
    await module.users.set_state("op", LOCKED)
    with pytest.raises(AuthError):
        await module.login("op", {"password": "oppass12"})


async def test_reset_state_forces_change_then_clears(ctx):
    module, _, _ = ctx
    await module.users.set_state("op", PASSWORD_RESET_REQUIRED)
    res = await module.login("op", {"password": "oppass12"})
    assert res["principal"]["must_change_password"] is True
    await module.change_password(res["token"], "oppass12", "newpass12")
    assert (await module.users.get("op"))["state"] == "ACTIVE"
    # new password works, old does not
    await module.login("op", {"password": "newpass12"})
    with pytest.raises(AuthError):
        await module.login("op", {"password": "oppass12"})


async def test_change_password_policy_enforced(ctx):
    module, _, _ = ctx
    res = await module.login("op", {"password": "oppass12"})
    with pytest.raises(PolicyError):
        await module.change_password(res["token"], "oppass12", "short")


async def test_no_auth_authenticator_accepts_anything():
    module, core, db = await _build(authenticator="no_auth")
    try:
        res = await module.login("admin", {"password": "whatever-wrong"})
        assert core.auth.verify(res["token"]).subject == "admin"
    finally:
        await db.close()


# --- REST ------------------------------------------------------------------


def _client(module, core=None):
    app = FastAPI()
    if core is not None:
        app.state.auth = core.auth  # required for the AUTH.MANAGE_USERS gate
    app.include_router(module.router)
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def _bearer(c, username, password):
    r = await c.post("/auth/login", json={"username": username, "credential": {"password": password}})
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def test_rest_login_me_logout(ctx):
    module, _, _ = ctx
    async with _client(module) as c:
        r = await c.post("/auth/login", json={"username": "admin", "credential": {"password": "admin123"}})
        assert r.status_code == 200
        token = r.json()["token"]
        bearer = {"Authorization": f"Bearer {token}"}

        me = await c.get("/auth/me", headers=bearer)
        assert me.status_code == 200 and me.json()["role"] == "super_admin"

        assert (await c.get("/auth/me")).status_code == 401  # no token

        out = await c.post("/auth/logout", headers=bearer)
        assert out.status_code == 200
        assert (await c.get("/auth/me", headers=bearer)).status_code == 401


async def test_rest_login_bad_credentials(ctx):
    module, _, _ = ctx
    async with _client(module) as c:
        r = await c.post("/auth/login", json={"username": "admin", "credential": {"password": "x"}})
        assert r.status_code == 401


# --- user management (gated AUTH.MANAGE_USERS) -----------------------------


async def test_user_management_full_flow(ctx):
    module, core, _ = ctx
    async with _client(module, core) as c:
        admin = await _bearer(c, "admin", "admin123")

        # create
        created = await c.post("/auth/users", headers=admin,
                               json={"username": "bob", "password": "bobpass12", "role": "operator"})
        assert created.status_code == 201

        # list + get
        listed = await c.get("/auth/users", headers=admin)
        assert "bob" in [u["username"] for u in listed.json()]
        assert (await c.get("/auth/users/bob", headers=admin)).json()["role"] == "operator"

        # assign role
        rr = await c.put("/auth/users/bob/role", headers=admin, json={"role": "engineer"})
        assert rr.json()["role"] == "engineer"

        # lock -> bob cannot login; unlock -> can
        await c.post("/auth/users/bob/lock", headers=admin)
        assert (await c.post("/auth/login", json={"username": "bob", "credential": {"password": "bobpass12"}})).status_code == 401
        await c.post("/auth/users/bob/unlock", headers=admin)
        assert (await c.post("/auth/login", json={"username": "bob", "credential": {"password": "bobpass12"}})).status_code == 200

        # reset-password -> temp returned, RESET state, old password dead
        reset = await c.post("/auth/users/bob/reset-password", headers=admin, json={})
        temp = reset.json()["temp_password"]
        assert temp
        relog = await c.post("/auth/login", json={"username": "bob", "credential": {"password": temp}})
        assert relog.status_code == 200 and relog.json()["principal"]["must_change_password"] is True


async def test_user_management_errors(ctx):
    module, core, _ = ctx
    async with _client(module, core) as c:
        admin = await _bearer(c, "admin", "admin123")
        dup = await c.post("/auth/users", headers=admin,
                           json={"username": "admin", "password": "whatever1", "role": "operator"})
        assert dup.status_code == 409
        assert (await c.get("/auth/users/ghost", headers=admin)).status_code == 404
        weak = await c.post("/auth/users", headers=admin,
                            json={"username": "x", "password": "short", "role": "operator"})
        assert weak.status_code == 422


async def test_super_admin_protected(ctx):
    module, _, _ = ctx
    from modules.auth.users import ProtectedUserError
    with pytest.raises(ProtectedUserError):
        await module.deactivate("admin")
    with pytest.raises(ProtectedUserError):
        await module.lock("admin")
    with pytest.raises(ProtectedUserError):
        await module.set_user_role("admin", "operator")
    # non-protected users are unaffected
    await module.deactivate("op")
    assert (await module.users.get("op"))["state"] == "INACTIVE"


async def test_super_admin_singleton(ctx):
    module, _, _ = ctx
    from modules.auth.users import ProtectedUserError
    with pytest.raises(ProtectedUserError):
        await module.create_user("admin2", "Password12", "super_admin")
    with pytest.raises(ProtectedUserError):
        await module.set_user_role("op", "super_admin")


async def test_super_admin_self_heals_on_boot(ctx):
    module, _, _ = ctx
    await module.users.set_state("admin", "INACTIVE")   # simulate the accident
    assert (await module.users.get("admin"))["state"] == "INACTIVE"
    await module.init()                                  # reboot path
    assert (await module.users.get("admin"))["state"] == "ACTIVE"


async def test_super_admin_password_reset_still_allowed(ctx):
    module, _, _ = ctx
    r = await module.admin_reset_password("admin")       # password op is the exception
    assert "temp_password" in r


async def test_user_management_permission_gated(ctx):
    module, core, _ = ctx
    async with _client(module, core) as c:
        # operator lacks AUTH.MANAGE_USERS -> 403
        op = await _bearer(c, "op", "oppass12")
        assert (await c.get("/auth/users", headers=op)).status_code == 403
        # no token -> 401
        assert (await c.get("/auth/users")).status_code == 401
