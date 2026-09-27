# Facts & figures

Generated from the code by `tools/gen_devguide.py` — never edited by hand. If a fact is wrong, the code
(or the generator) is wrong. A CI test fails when these files are out of date, so they always describe the
framework version shown on the [start page](help:dev-guide-start).

Framework version:

```tmf:facts
version
```

## Modules

```tmf:facts
modules
```

## Permissions × default roles

`●` = granted by the role's default configuration (wildcards like `RECIPE.*` expanded). Live grants are
edited on the Permissions screen; existing stations pick up new permissions with
`python -m tools.config_doctor --apply` and a re-login.

```tmf:permissions-matrix
```

## Controller MQTT ops

Hardware operations run on a worker pool so a slow instrument never blocks other ops.

```tmf:facts
ops
```

## Instrument capabilities

```tmf:facts
capabilities
```

## Screens and what they need

```tmf:facts
routes
```

## Skills

```tmf:facts
skills
```

Raw data: `docs/generated/facts.json` (machine-readable) and `facts.md` (digest) in the repo.
