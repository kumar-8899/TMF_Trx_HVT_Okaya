# Your first app in 30 minutes

You will fork the framework, describe a bench, get a running app that passes in **simulation** (no
hardware needed), and open it in the UI. The details behind each step are in
[Developer onboarding](help:dev-onboarding); this page is the guided version.

```tmf:checklist
- Install Git, Python 3.11+, Node.js and Claude Code
- Clone Super_Test_App and Instrument_Library (side by side)
- Install the skills (copy plugins/tmf-tools/skills to ~/.claude/skills) and restart Claude Code
- Set FRAMEWORK_REMOTE and TMF_INSTRUMENT_LIBRARY, then reopen Claude Code
- Create an empty GitHub repo for the new app (each app is its own repo)
- Run the new-test-app skill (or clone-test-app) and answer its questions
- Let it install dependencies (pip editable installs + npm install inside frontend/)
- python app/<slug>/tools/run_sim.py prints VERDICT: PASS
- python -m pytest app/<slug>/tests -q is green
- python station.py opens the app; log in admin / admin and change the password
- Configure your instrument instances on Config → Instruments, then restart
```

## What the skill does for you

1. **Forks a release tag** (never `main`) and wires the remotes: `upstream` = the framework
   (read-only, push disabled), `origin` = your app's own repo.
2. Copies only the **drivers you need** from the central Instrument_Library into your fork
   (self-contained: the app never references the central repo at runtime).
3. Scaffolds the **app payload** under `app/<slug>/` — variable map, step-type package, recipe,
   `controller.json`, test specs, a simulation runner and tests.
4. Wires `backend/config/app.json`, installs everything and **verifies in simulation**.

Not sure which skill? → [Which skill?](help:dev-guide-which-skill)

## After it works

- Read [Ownership boundary](help:dev-guide-ownership) **before** you edit anything outside `app/<slug>/`.
- Add tests one at a time in dependency order → [Building blocks](help:dev-guide-building-blocks).
- Cut your first release with `deploy/cut-release.ps1` (the one build/release entry point) →
  [Cutting a release](help:dev-release-howto), [Deploying to a station](help:dev-deploy-station).
- Stay current with framework releases → [What's new & upgrading](help:dev-guide-whats-new).

## If something fails

Most first-run trouble is one of the [Gotchas](help:dev-guide-gotchas): `npm install` not run inside
`frontend/`, editable installs pointing at a *different* fork, or a missing broker on `:1883`.
