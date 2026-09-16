# Developer Onboarding

How to start building test apps on the framework, on your own machine. No dependency on anyone
else's PC. Follow the steps in order.

> For now, apps run in **dev mode** (no license needed). You keep your app up to date by pulling
> from the framework with git. Signing and licensing come later.

---

## Step 1 — Install the tools

On your machine, install:
- **Git** — https://git-scm.com
- **Python 3.11+** — https://python.org
- **Node.js** — https://nodejs.org
- **Claude Code**

Then ask the maintainer to give you access to these GitHub repos:
- Framework: `https://github.com/kumar-8899/Super_Test_App`
- Instrument library: `https://github.com/kumar-8899/Instrument_Library`

The first time you `git clone`, Git will ask you to sign in to GitHub — do that once.

---

## Step 2 — Get the two repos

Pick a folder (example uses `C:\dev`) and clone both:

```powershell
git clone https://github.com/kumar-8899/Super_Test_App.git C:\dev\Super_Test_App
git clone https://github.com/kumar-8899/Instrument_Library.git C:\dev\Instrument_Library
```

- **Super_Test_App** = the framework. It also contains the skills.
- **Instrument_Library** = the shared drivers for instruments (power supplies, loads, meters…).

---

## Step 3 — Install the skills

The skills are the helpers that build apps for you (create a new app, add a test, add a driver).

**Easiest way — ask Claude to install them.** Open Claude Code and type:

```
Copy the skills from C:\dev\Super_Test_App\plugins\tmf-tools\skills
to my global Claude skills folder and confirm they're installed.
```

Claude copies them to your global skills folder (`C:\Users\<you>\.claude\skills`). After that the
skills work in **every** project you open:
- **new-test-app** — make a new app
- **clone-test-app** — make a new app by cloning an existing similar app instead of starting blank
- **system-blueprint** — turn a spreadsheet of a system's I/O into an app's variable map
- **add-bench-test** — add a test to an app
- **test-step-authoring** — add a new kind of test step
- **create-instrument-library** — add a driver for a new instrument

(If you prefer to do it by hand, run this in the framework folder instead:
`Copy-Item -Recurse -Force .\plugins\tmf-tools\skills\* "$env:USERPROFILE\.claude\skills\"`.)

Restart Claude Code once so it picks up the new skills.

---

## Step 4 — Set two environment variables

These tell the skills where the framework and the instrument library live, so they work on any
machine. In PowerShell (run once):

```powershell
setx FRAMEWORK_REMOTE "https://github.com/kumar-8899/Super_Test_App.git"
setx TMF_INSTRUMENT_LIBRARY "C:\dev\Instrument_Library"
```

- `TMF_INSTRUMENT_LIBRARY` must point to where **you** cloned Instrument_Library in Step 2.
- `setx` saves them permanently. **Close and reopen** Claude Code so they take effect.

---

## Step 5 — Make a new app

In Claude Code, run the **new-test-app** skill (just describe your bench, or type
`/new-test-app`). Give it:
- the app name and customer,
- how many test stations,
- the instruments and what each one does,
- the tests to run and their pass/fail limits (from the product spec).

It creates the app in its own folder and its own GitHub repo, copies the drivers it needs,
scaffolds everything, installs dependencies, and checks that the tests pass in simulation.

> Each app is its **own** GitHub repo. Create an empty repo for it first (or ask the maintainer),
> and give its URL to the skill when asked.

**Already have a similar app?** If another app you (or your team) built is close to what you
need — same or overlapping instruments, similar test sequence — use **clone-test-app** instead:
it still forks a clean framework tag (so the new app's history and upgrade path are correct),
but reuses the existing app's tests/instruments/UI as a starting point instead of you re-typing
them, then walks you through re-checking every limit against the new customer's spec.

---

## Step 6 — Run the app

```powershell
cd <your-app-folder>
python station.py
```

A window opens with the app. Log in with `admin` / `admin`. Set up your instruments on the
**Config → Instruments** page, then restart.

(For live UI development with instant reload, use `python station.py --dev` instead.)

---

## Step 7 — Keep the app up to date

When the framework gets a new version, pull it into your app:

```powershell
cd <your-app-folder>
git fetch upstream --tags
git merge vX.Y.Z
python -m tools.config_doctor --apply
```

`vX.Y.Z` is the framework version you want (ask the maintainer, or check the framework's
Releases page).

---

## Step 8 — Suggest a change to the framework itself

Your app never edits framework files directly. To change the framework: open the **framework**
folder, make your change on a new branch, and open a Pull Request to
`kumar-8899/Super_Test_App`. Once it's merged and released, your app gets it through Step 7.

---

## Which skill for which job

| You want to… | Skill |
|--------------|-------|
| Start a new app | `new-test-app` |
| Start a new app that's similar to one you already have | `clone-test-app` |
| Turn a spreadsheet of a system's I/O into an app's variable map | `system-blueprint` |
| Add a test to an app | `add-bench-test` |
| Add a new kind of test step | `test-step-authoring` |
| Add a driver for a new instrument | `create-instrument-library` |

---

### Note for terminal users

If you use the **terminal** `claude` command (not the app), you can install the skills the
packaged way instead of Step 3:

```
/plugin marketplace add kumar-8899/Super_Test_App
/plugin install tmf-tools
```

`/plugin` only works at the `claude` prompt in a terminal — not in the Claude Code app. In the
app, use Step 3.
