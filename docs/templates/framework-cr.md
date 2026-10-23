# CR-<n> — <one-line title>

| | |
|---|---|
| Raised by | <app / developer> |
| Date | <yyyy-mm-dd> |
| Framework version | <e.g. v1.31.1> (base tag of this fork) |
| App / version | <slug> <version> |
| Where seen | <dev PC / bench / customer site> |
| Severity | <blocks release / blocks a customer / annoyance> |
| Generic or app-specific? | <generic -> framework; app-specific -> stays in the app> |

## Symptom
What happened, in the user's terms. Exact error text, verbatim.

## Evidence
- Command / steps to reproduce:
- Output / log excerpt / debug bundle (path or `bench_why` result):
- What was ruled out:

## Root cause
Where and why, with `path/to/file.py:line` references into the framework source.

## Proposed change
Summary, then the diff: [`CR-<n>.diff`](CR-<n>.diff). Files touched:
- `path/one`
- `path/two`

## Test
The test that FAILS without the change and passes with it (name + location). If it cannot be tested here
(real hardware, real SQL Server, frozen build), say so and say what a person must verify, and how.

## Who is affected
Which forks / builds / customers; whether existing stations need `config_doctor --apply`, a migration, or a re-login.

## Docs
Which docs/help pages change (the docs are the contract).

## Status
- [ ] raised  - [ ] accepted  - [ ] released in framework v____  - [ ] merged into this fork
