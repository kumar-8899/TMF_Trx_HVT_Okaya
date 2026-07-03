"""Python instrument library — framework core (INSTRUMENT_LIBRARY.md).

Ships the fat base, capability interfaces, deterministic fault-injection transport,
the registration decorator + index generator, and the conformance suite. The
per-instrument library classes live in a SEPARATE repo and are gated by this
conformance suite as external subjects (§0, §8).
"""

from instrumentlib.base import (
    InstrumentBase,
    emergency_disable_all,
    registered_instances,
)
from instrumentlib.errors import (
    CommandTimeout,
    DeviceError,
    GarbageResponse,
    IdentityMismatch,
    InstrumentError,
    NotConnected,
    NotSupported,
    TransportDisconnected,
)
from instrumentlib.interfaces import (
    CAPABILITIES,
    NON_SCALAR_CAPABILITIES,
    SCALAR_CAPABILITIES,
    Capability,
    DSO,
    IAnalogInput,
    IDigitalInput,
    IDigitalOutput,
    IElectronicLoad,
    IPowerSource,
    ITemperature,
    Multiplexer,
)
from instrumentlib.registry import REGISTRY, build_index, instrument_library
from instrumentlib.transport import FaultPlan, FaultTransport, SimTransport, Transport

__all__ = [
    "InstrumentBase", "emergency_disable_all", "registered_instances",
    "instrument_library", "build_index", "REGISTRY",
    "Transport", "SimTransport", "FaultTransport", "FaultPlan",
    "Capability", "CAPABILITIES", "SCALAR_CAPABILITIES", "NON_SCALAR_CAPABILITIES",
    "IPowerSource", "IElectronicLoad", "IAnalogInput", "IDigitalInput",
    "IDigitalOutput", "ITemperature", "Multiplexer", "DSO",
    "InstrumentError", "NotConnected", "NotSupported", "DeviceError",
    "CommandTimeout", "GarbageResponse", "IdentityMismatch", "TransportDisconnected",
]
