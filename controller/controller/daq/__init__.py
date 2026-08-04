"""DAQ — nidaqmx-backed AI/DI streaming + reads (PYTHON_CONTROLLER.md §9.5). Sim-capable
so CI + demos run with no card; the real source lazy-imports nidaqmx."""

from controller.daq.source import make_source
from controller.daq.controller import DaqController, register_daq_ops

__all__ = ["DaqController", "register_daq_ops", "make_source"]
