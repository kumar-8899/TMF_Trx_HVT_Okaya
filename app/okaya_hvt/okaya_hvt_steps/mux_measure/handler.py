"""mux_measure — route a tap through the multiplexing relays, read it, compare to limits.

The bench shares one meter front-end across Primary / Secondary / Feedback / Winding taps; the
Waveshare relays select which tap is connected. This step energises the relays named in
`route`, settles, reads `read_signal`, and produces ONE Measurement judged against [min, max].
It ALWAYS opens the route again in a `finally`, so a read error or abort can never leave a tap
energised (r3/safety). Relay names, the signal to read, and the limits are all recipe
parameters — the exact relay combination per measurement is site wiring, kept as data.
"""

from __future__ import annotations

from controller.registry import register_step_type
from controller.results import Limits, Measurement, StepResult


@register_step_type(
    type_id="mux_measure",
    display_name="Multiplex + measure",
    schema_path="schema.json",
    composite=False,
)
class MuxMeasure:
    @staticmethod
    def bindings(params):
        route = list(params.get("route") or [])
        sig = params.get("read_signal")
        return {"signals": route + ([sig] if sig else []), "actions": []}

    def execute(self, params, ctx) -> StepResult:
        route = list(params.get("route") or [])
        read_signal = params["read_signal"]
        settle_s = float(params.get("settle_s", 0.2))
        name = params.get("name") or read_signal
        limits = Limits(min=params.get("min"), max=params.get("max"))

        for sig in route:
            ctx.write(sig, 1)
        try:
            ctx.wait(settle_s)
            value = ctx.read(read_signal)      # a failed read raises — never a silent default
            return StepResult(measurements=[
                Measurement(name, value, params.get("unit"), limits=limits)])
        finally:
            for sig in route:
                ctx.write(sig, 0)
