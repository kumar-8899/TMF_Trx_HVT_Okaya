# Developer glossary

| Term | Meaning |
|---|---|
| **Framework** | This repo (Super_Test_App): the platform. Never an application. |
| **App / fork** | A separate repo, forked from a framework **release tag**, that adds its own payload. |
| **Upstream** | The framework remote in a fork — read-only (push disabled). `origin` is the app's own repo. |
| **App payload** | Everything under `app/<name>/`: step types, variable maps, recipes, specs, `controller.json`. |
| **Ownership boundary** | Which paths an app may edit ([details](help:dev-guide-ownership)). |
| **Module / variant** | A module is a contract (recipe, report, health…); a variant is one implementation. |
| **Core** | The small shared layer modules depend on: db, config, auth verify, diagnostics, web shell. |
| **Controller** | Owns test execution + hardware; LabVIEW or standalone Python, one active per PC. |
| **Station / socket** | A test position; one PC can run several (`st1…stN`). |
| **Step type** | A kind of test step (8 core types + app packages); its schema defines the recipe params. |
| **Recipe** | Data: ordered `{type, id, params}` steps and limits. |
| **Variable map** | Named signals and actions bound to instrument capabilities. |
| **Capability** | A typed instrument interface (power source, DMM, multiplexer…) a driver implements. |
| **Driver / instrument library** | A class implementing capabilities for one instrument model. |
| **Instrument instance** | A configured instrument (id, driver, params, *simulated*), created on Config → Instruments. |
| **Simulated** | A per-instrument toggle — there is no global simulation mode. |
| **Spec** | The human-readable, authoritative description of one test (`specs/<test>.md`). |
| **Skill** | A Claude Code workflow shipped with the framework (new-test-app, add-bench-test…). |
| **Track** | Build track: `framework` (git tag only) or `app` (full frozen build with `cut-release.ps1`). |
| **`run.dist`** | The frozen backend folder — the unit an in-app update swaps. |
| **RAG envelope** | The common metadata every persisted record carries (`id, type, ts, station, source_version, summary`). |
| **Drift gate** | A test that fails when docs/generated data and code disagree. |
