# ADR 0001 — No centralized MQTT topic-mapping window

**Status:** Accepted · **Date:** 2026-06 · **Area:** bridge / variables

## Context
Proposed: a UI + shared registry mapping `variable -> MQTT topic`, read by both
LabVIEW and Python at init to drive subscribe/publish. Goal: one source of truth,
both sides in sync.

## Decision
**Rejected.** Topics stay **rule-derived** from the fixed grammar
(`LABVIEW_BRIDGE.md` §3: `tmf/{station}/{class}/{name}`, where QoS/retain/direction
are class properties). A variable's topic is already a pure function
(`value/{name}`); a mapping table only restates the rule and drops class
semantics.

## Why (blunt)
1. **Bootstrap paradox** — you can't deliver the definition of MQTT topics *over*
   MQTT at init without a hard-coded fixed topic + retained blob + start-ordering.
   The rule-derivation approach has zero ordering coupling.
2. **Fleet footgun** — §11 makes topic renames breaking; the fleet dashboard +
   uplink subscribe `tmf/+/{value,event,…}/#`. A remap window lets a station go
   silently invisible to the fleet.
3. **Two parsers, more drift** — both sides would parse an identical registry
   format; today they share a one-line rule.
4. **YAGNI** (PRINCIPLES §6) — solves nothing the Variable Engine won't solve
   better.

## Instead (when the DAQ/HAL vertical lands)
- **Variable Engine catalog** (`labview/variables.json`) is the single shared
  truth: `{name, units, direction, scaling, limits, alias?}`. Both sides load it
  at init; **topics are computed, never stored**.
- **`alias`** field covers the only real mapping need (legacy LV tag → canonical
  variable); the topic still derives from the canonical name.
- A **read-only** "Variables / Topics" UI view (discovery, not editing) renders
  derived topics. MQTT Explorer on `tmf/#` covers live traffic.
- The central registry that *should* exist already does: `LABVIEW_BRIDGE.md` §3
  (the grammar) — that is what is centralized, not per-variable strings.
