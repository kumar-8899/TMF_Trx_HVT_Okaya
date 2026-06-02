"""Registry + discovery (CORE.md §2.1)."""

import pytest

from core.framework.registry import Registry, RegistryError


def test_register_and_lookup():
    reg = Registry()

    @reg.register_module("auth", contract=object, contract_version=1, display_name="Auth")
    class AuthBase:
        pass

    @reg.register_variant("auth", "local_db", display_name="Local DB")
    class LocalDb(AuthBase):
        pass

    rec = reg.get("auth")
    assert rec.display_name == "Auth"
    assert rec.variant_ids == ["local_db"]
    assert reg.variant("auth", "local_db") is LocalDb
    assert rec.contract_id == "auth"


def test_duplicate_module_fails_loud():
    reg = Registry()

    @reg.register_module("a", contract=object)
    class A:
        pass

    with pytest.raises(RegistryError):

        @reg.register_module("a", contract=object)
        class A2:
            pass


def test_duplicate_variant_fails_loud():
    reg = Registry()

    @reg.register_module("a", contract=object)
    class A:
        pass

    @reg.register_variant("a", "v1")
    class V1(A):
        pass

    with pytest.raises(RegistryError):

        @reg.register_variant("a", "v1")
        class V1Dup(A):
            pass


def test_variant_before_module_fails():
    reg = Registry()
    with pytest.raises(RegistryError):

        @reg.register_variant("ghost", "v1")
        class V1:
            pass


def test_unknown_lookups_raise_not_null():
    reg = Registry()
    with pytest.raises(RegistryError):
        reg.get("nope")

    @reg.register_module("a", contract=object)
    class A:
        pass

    with pytest.raises(RegistryError):
        reg.variant("a", "missing")
