# Developer Hub

This is the starting point for anyone **building test applications on the framework**. It shows the
framework as it is *right now*: the numbers, tables and diagrams on these pages are generated from the
code, so they can't drift from it.

Framework version:

```tmf:facts
version
```

> **This hub is for developers only.** It exists in the source checkout (yours, and every fork's) and is
> never packaged into a client station — customers get the User portal/manual instead.

## Pick your path

| I want to… | Go to |
|---|---|
| Build my first app | [Your first app in 30 minutes](help:dev-guide-first-app) |
| Start from an app we already have | [Which skill?](help:dev-guide-which-skill) → `clone-test-app` |
| Understand how the pieces fit | [Mental model](help:dev-guide-mental-model) |
| Know what I may edit in a fork | [Ownership boundary](help:dev-guide-ownership) |
| Add a test / step type / driver | [Building blocks](help:dev-guide-building-blocks) |
| Look something up (modules, permissions, ops…) | [Facts & figures](help:dev-guide-facts) |
| See what changed since my fork | [What's new & upgrading](help:dev-guide-whats-new) |
| Avoid a mistake others already made | [Gotchas & FAQ](help:dev-guide-gotchas) |

## The whole system in one picture

```tmf:diagram
architecture
```

Three tiers, two seams: the **controller** runs the test and owns the hardware, the **Python backend**
is the app platform and the only web edge, the **React frontend** talks only to the backend. The seam
between controller and backend is MQTT; the seam between backend and frontend is HTTP + WebSocket.

## How to use these pages

- **Widgets are live.** Try the [ownership explorer](help:dev-guide-ownership) or the
  [skill picker](help:dev-guide-which-skill); tick off the [first-app checklist](help:dev-guide-first-app).
- **The docs are the contract.** Decide → update the doc → build against the doc. The design documents
  (principles, contracts, architecture) are linked from every page; this hub is the map, they are the law.
- **Found a gap or a bug?** Framework changes go upstream as a release — never a downstream patch
  ([why](help:dev-guide-ownership)). Add what you learned to [Gotchas](help:dev-guide-gotchas).
