"""LOGS.md §12 - the central audit hook: every state-changing request is recorded, failures reach the
error log, secrets never do, and the exception handler no longer swallows crashes."""

import types

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from core.services.audit import READ_ONLY_POSTS, action_name, is_read_only_post
from core.services.auth_verify import AuthError, Principal
from core.services.web import install_web


class _Diag:
    def __init__(self):
        self.events = []

    def _add(self, level, sub, msg, **ctx):
        self.events.append((level, sub, msg, ctx))
        return {}

    def error(self, sub, msg, **c): return self._add("error", sub, msg, **c)
    def warning(self, sub, msg, **c): return self._add("warning", sub, msg, **c)
    def info(self, sub, msg, **c): return self._add("info", sub, msg, **c)

    def exception(self, sub, msg, exc=None, **c):
        return self._add("error", sub, msg, exc=type(exc).__name__ if exc else None, **c)


class _Logs:
    def __init__(self):
        self.actions = []

    async def record_action(self, principal, action, target, result, detail=None):
        self.actions.append({"user": principal.subject, "role": principal.role, "action": action,
                             "target": target, "result": result, "detail": detail or {}})
        return "id"


class _Auth:
    def verify(self, token):
        if token != "good":
            raise AuthError("bad token")
        return Principal("alice", role="engineer", permissions=frozenset({"X"}))


@pytest.fixture
def env():
    app = FastAPI()
    install_web(app)
    diag, logs = _Diag(), _Logs()
    app.state.auth = _Auth()
    app.state.core = types.SimpleNamespace(diag=diag, contracts={"logs": logs})

    @app.post("/auth/login")
    async def login(body: dict):
        if body.get("credential", {}).get("password") != "right":
            raise HTTPException(status_code=401, detail="bad credentials")
        return {"token": "good"}

    @app.post("/recipes/{recipe_id}/drafts/{draft_id}/publish")
    async def publish(recipe_id: str, draft_id: str, body: dict):
        return {"ok": True}

    @app.post("/variables/read")
    async def read(body: dict):
        return {"v": 1}

    @app.put("/config/shift")
    async def shift(body: dict):
        raise HTTPException(status_code=403, detail="requires permission(s): CONFIG.EDIT")

    @app.post("/runs/start")
    async def start(body: dict):
        raise RuntimeError("controller exploded")

    @app.get("/boom")
    async def boom():
        raise ValueError("get crashed")

    return TestClient(app, raise_server_exceptions=False), diag, logs


H = {"Authorization": "Bearer good"}


def test_mutating_request_is_recorded_with_principal_target_and_result(env):
    c, diag, logs = env
    r = c.post("/recipes/r1/drafts/d9/publish", json={"note": "hi", "secret_field": "S3CR3T"}, headers=H)
    assert r.status_code == 200
    (a,) = logs.actions
    assert (a["user"], a["role"], a["action"], a["target"], a["result"]) == (
        "alice", "engineer", "recipe.publish", "r1/d9", "success")
    assert a["detail"]["status"] == 200 and a["detail"]["fields"] == ["note", "secret_field"]
    assert "S3CR3T" not in repr(logs.actions) and "S3CR3T" not in repr(diag.events)  # values never stored


def test_failed_login_is_recorded_with_username_but_never_the_password(env):
    c, diag, logs = env
    r = c.post("/auth/login", json={"username": "bob", "credential": {"password": "wrong-pw-123"}})
    assert r.status_code == 401
    (a,) = logs.actions
    assert (a["user"], a["action"], a["result"]) == ("bob", "auth.login", "failure")
    assert "bad credentials" in a["detail"]["reason"]
    assert "wrong-pw-123" not in repr(logs.actions) and "wrong-pw-123" not in repr(diag.events)


def test_successful_login_attributes_to_the_username(env):
    c, _, logs = env
    assert c.post("/auth/login", json={"username": "alice", "credential": {"password": "right"}}).status_code == 200
    assert (logs.actions[0]["user"], logs.actions[0]["result"]) == ("alice", "success")


def test_read_only_post_is_not_an_action(env):
    c, _, logs = env
    assert c.post("/variables/read", json={"names": ["a"]}, headers=H).status_code == 200
    assert logs.actions == []


def test_forbidden_is_a_failed_action_and_a_security_warning(env):
    c, diag, logs = env
    assert c.put("/config/shift", json={"x": 1}, headers=H).status_code == 403
    assert logs.actions[0]["result"] == "failure" and logs.actions[0]["action"] == "config.shift"
    assert any(lv == "warning" and sub == "security" for lv, sub, *_ in diag.events)


def test_handler_crash_is_logged_with_its_exception_and_audited_as_failure(env):
    c, diag, logs = env
    assert c.post("/runs/start", json={}, headers=H).status_code == 500
    assert logs.actions[0]["result"] == "failure" and "controller exploded" in logs.actions[0]["detail"]["reason"]
    assert any(sub == "http" and ctx.get("exc") == "RuntimeError" for _, sub, _, ctx in diag.events)


def test_unhandled_get_exception_is_no_longer_swallowed(env):
    c, diag, logs = env
    assert c.get("/boom").status_code == 500
    assert any(sub == "http" and ctx.get("exc") == "ValueError" for _, sub, _, ctx in diag.events)
    assert logs.actions == []   # GETs are never actions


def test_audit_failure_never_breaks_the_request(env):
    c, _, logs = env
    async def broken(*a, **k): raise RuntimeError("db down")
    logs.record_action = broken
    assert c.post("/recipes/r1/drafts/d1/publish", json={}, headers=H).status_code == 200


def test_unknown_routes_get_a_generic_name_and_readonly_list_is_explicit():
    assert action_name("POST", "/foo/{id}/bar") == "post /foo/{id}/bar"
    assert is_read_only_post("/variables/read")
    assert not is_read_only_post("/variables/write")                          # a write IS audited
    assert len(READ_ONLY_POSTS) < 15                                          # keep the exception list small


def test_apps_can_register_their_own_read_only_posts_and_names():
    from core.services import audit
    n = len(audit.READ_ONLY_POSTS)
    try:
        audit.register_read_only_post(r"^/myapp/probe$")
        audit.register_action_name("post", "/myapp/go", "myapp.go")
        assert is_read_only_post("/myapp/probe") and action_name("POST", "/myapp/go") == "myapp.go"
    finally:
        del audit.READ_ONLY_POSTS[n:]
        audit._ACTION_NAMES.pop(("POST", "/myapp/go"), None)


async def test_audit_tables_match_real_routes(config_dir):
    """CI guard (LOGS.md section 12): the audit middleware is on the real app, and every read-only pattern /
    friendly name refers to a route that exists - a renamed route can no longer silently drop out of the
    audit tables. Mutating routes are audited by default, so a new endpoint needs no registration."""
    from core.app import create_app
    from core.services import audit
    app = create_app(config_dir=config_dir, db_path=":memory:", enable_bridge=False)
    async with app.router.lifespan_context(app):
        routes = {(m, r.path) for r in app.routes for m in (getattr(r, "methods", None) or ())
                  if m in audit.MUTATING}
        assert routes, "no mutating routes found"
        templates = {t for _, t in routes}
        for pat in audit.READ_ONLY_POSTS:
            assert any(pat.match(t) for t in templates), f"stale read-only pattern {pat.pattern}"
        for key in audit._ACTION_NAMES:
            assert key in routes, f"action name for non-existent route {key}"
        # the exemption list only ever applies to POST - a PUT/PATCH/DELETE template must not match it
        assert not [(m, t) for m, t in routes if m != "POST" and audit.is_read_only_post(t)]
