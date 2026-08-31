# Developer Onboarding — building on the framework from any machine

Get a new developer productive on the Super_Test_App framework **without any dependency on the
maintainer's PC**. Everything below works from a fresh Windows machine with Python 3.11+, Node,
Git, and Claude Code installed.

> Status: personal-GitHub phase. Licensing/signing is **deferred** — apps run in **dev mode**
> (stub licensing). Framework updates come via **git merge** from `upstream` tags, not the signed
> in-app updater. When the org + Keystation land, only remote URLs change (see `docs/TEMPLATE.md`).

## 1. Access

Ask the maintainer for collaborator access to:
- **Framework:** `https://github.com/kumar-8899/Super_Test_App`
- **Instrument library:** `Instrument_Library` repo (once pushed — see below)
- Your app's repo is created per app (step 4).

Configure git auth (HTTPS credential manager or SSH) so you can clone **private** repos —
Claude Code's `/plugin marketplace add` needs the same auth to fetch the framework.

## 2. Get the skills

Four skills: `new-test-app`, `test-step-authoring`, `add-bench-test`, `create-instrument-library`.
Pick the method for how you run Claude Code:

**A. Claude Code interface / agent mode (most devs).** Skills load as **project skills** from
`.claude/skills/` in the repo you open. Just **clone and open the framework repo** — the four
skills are committed there, so they're available automatically (and every fork made with
`new-test-app` inherits them). No `/plugin`, no plugin.json.

```
git clone https://github.com/kumar-8899/Super_Test_App.git
# open this folder in the Claude Code interface — skills are ready
```

To have them in **every** repo/session, copy them once to your global skills dir:
```powershell
Copy-Item -Recurse -Force .\.claude\skills\* "$env:USERPROFILE\.claude\skills\"
```

**B. Terminal `claude` CLI (only if you use it).** The framework repo is also a Claude Code
**marketplace**:
```
/plugin marketplace add kumar-8899/Super_Test_App
/plugin install tmf-tools
```
`/plugin` is a slash command at the `claude` prompt (not PowerShell); it is **not** available in
the interface/agent mode — use method A there. Update later with `/plugin marketplace update`.

> The same four skills live in two places in the repo — `.claude/skills/` (method A) and
> `plugins/tmf-tools/skills/` (the plugin, method B). Keep them in sync when editing a skill.
> `plugin.json` (`plugins/tmf-tools/.claude-plugin/plugin.json`) only matters for method B.

## 3. Environment

Set these once (User environment variables), so the skills and controller are machine-independent:

| Variable | Value |
|----------|-------|
| `FRAMEWORK_REMOTE` | `https://github.com/kumar-8899/Super_Test_App.git` (default; override for a fork/org) |
| `TMF_INSTRUMENT_LIBRARY` | path to your local clone of the `Instrument_Library` repo |

```pwsh
git clone https://github.com/kumar-8899/Instrument_Library.git D:\dev\Instrument_Library
setx TMF_INSTRUMENT_LIBRARY D:\dev\Instrument_Library
```

## 4. Create a new app

1. Create the app's **own** GitHub repo first (each app is a separate repo):
   `gh repo create <org-or-user>/App_<Name> --private`
2. In Claude Code, run the **`new-test-app`** skill with your bench/product spec. It:
   clones the framework at a release tag from `$FRAMEWORK_REMOTE`, wires **`upstream`** = framework
   and **`origin`** = your app repo, copies the needed drivers from `$TMF_INSTRUMENT_LIBRARY`,
   scaffolds the app payload, installs deps, and verifies in simulation.

## 5. Run it (dev mode)

```pwsh
cd App_<Name>
python station.py            # native window; builds + serves the SPA, supervises the backend
# or:  python station.py --dev   (Vite + HMR)
```

Login `admin` / `admin`. Licensing is the stub (dev). Configure instrument instances on
**Config → Instruments** (the single source; ids match the variable map), then restart.

## 6. Update the app to a newer framework version

```pwsh
git fetch upstream --tags
git merge vX.Y.Z             # clean iff only app-owned paths were edited (docs/TEMPLATE.md §1)
python -m tools.config_doctor --apply
```

This is the supported upgrade path today. (The signed in-app updater — Settings → Updates — is a
later phase that needs Keystation; see `docs/UPDATES.md`.)

## 7. Suggest a change to the framework itself

App repos never patch framework files (the fork boundary, `docs/TEMPLATE.md` §1). To change the
framework: work in a **clone of the framework repo**, branch, and open a **PR to
`kumar-8899/Super_Test_App`**. Once merged and tagged, apps pick it up via step 6.

## Common tasks → skill

| Task | Skill |
|------|-------|
| New app / fork the framework | `new-test-app` |
| Add a test to an existing app | `add-bench-test` |
| Author a controller step type | `test-step-authoring` |
| Author an instrument driver | `create-instrument-library` |
