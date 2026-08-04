"""Python Test Controller — a standalone process that owns test execution for a
station set, a peer implementation of the same MQTT contract LabVIEW serves
(PYTHON_CONTROLLER.md). It imports NOTHING from the framework app (backend/): the
process boundary is real and enforced by a test (tester/test_no_backend_import.py)."""

__version__ = "0.1.0"
