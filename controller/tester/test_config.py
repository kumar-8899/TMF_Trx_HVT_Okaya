"""Controller config load + validation (PYTHON_CONTROLLER.md §4)."""

import pytest

from controller.config import ConfigError, parse_config


def _base(**over):
    d = {"schema_version": 1, "broker": {"host": "10.0.0.5", "port": 1884},
         "stations": [{"station": "st1", "variable_map": "maps/st1.json"}]}
    d.update(over)
    return d


def test_parse_valid():
    cfg = parse_config(_base(stations=[{"station": "st1"}, {"station": "st2"}]))
    assert cfg.broker_host == "10.0.0.5" and cfg.broker_port == 1884
    assert [s.station for s in cfg.stations] == ["st1", "st2"]


def test_defaults():
    cfg = parse_config({"schema_version": 1, "stations": [{"station": "st1"}]})
    assert cfg.broker_host == "127.0.0.1" and cfg.broker_port == 1883
    assert cfg.abort_grace_ms == 2000 and cfg.teardown_timeout_ms == 30000


def test_bad_schema_version():
    with pytest.raises(ConfigError):
        parse_config(_base(schema_version=2))


def test_empty_stations_rejected():
    with pytest.raises(ConfigError):
        parse_config(_base(stations=[]))


def test_station_missing_id_rejected():
    with pytest.raises(ConfigError):
        parse_config(_base(stations=[{"variable_map": "x.json"}]))


def test_duplicate_station_rejected():
    with pytest.raises(ConfigError):
        parse_config(_base(stations=[{"station": "st1"}, {"station": "st1"}]))
