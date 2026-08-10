# App identity (Config)

*Super admin only.* Rebrand the app for a project without touching source or `app.json`.
Saved as a station override that applies **live** — reload to see it on the title bar,
login page, and header.

## Fields
- **Name** — the displayed app name (e.g. *Acme EOL Tester*).
- **Badge** — the 1–2 character glyph in the header/login tile.
- **Product / tab title** — browser tab text and the login subtitle.
- **Tagline** — the notice line on the login page.

## Logos
- **Client logo** — shown **top-left** in the header, beside the app name.
- **Exeliq logo** — shown **top-right** in the header.

Use *Choose file…* to pick a PNG/JPG/SVG (≤ 512 KB); a preview appears in place. The image
is stored with the branding record and applied live (reload to see it). *Clear* removes it.

Defaults come from `app.json` `branding` (TEMPLATE.md §1: an application rebrands via
config, never code edits). The form is also **step 1** of the *Setup wizard*.
