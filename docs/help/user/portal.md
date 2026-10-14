# User Portal

The portal is your one place for **how-to information about this station**: the manual, the hardware
documents (instrument manuals, wiring drawings) that belong to it, and — if your role allows — the
**Test Sequence** for this product. (It replaces the separate *Help* menu entry; pressing **F1** on any screen
still opens the quick help panel, whose *Open full help* button lands here.) Open it from **Portal** in the side menu.

![User Portal — the built-in manual](asset:portal)

## Manual

The **Manual** tab is the station's built-in manual: the same pages you reach with **F1** on any screen, plus —
under **This app** — pages written specifically for this bench (wiring, setup notes, procedures). Pages are
searchable, and links between pages stay inside the portal.

## Test Sequence

Shown only if your role has the **View test sequence** permission. It explains, step by step, what this product's
test does — what is measured, how it is wired, and what a limit means. This content is written by the people who
built this application, so it can differ from station to station; if the tab says it hasn't been published yet,
ask your application developer.

## Library

![User Portal library — searchable hardware manuals and drawings](asset:portal-library)

The **Library** tab holds PDFs: instrument manuals, datasheets, wiring and mechanical drawings.

- **Find** — type in the search box. It looks at titles, tags and the **text inside** the PDFs, and shows
  where each match is. Click a result to open it.
- **Read** — click the eye icon. The document opens in a full-screen viewer with page navigation, zoom,
  search and print. **Save a copy** puts a copy in this PC's **Downloads** folder.
- **Documents shipped with the app** are marked *shipped with the app* and are read-only.
- **Scanned PDFs** (photographs of pages) have no text to search; they are marked *not searchable* but can still
  be opened.

### Adding a document *(needs the "Add portal documents" permission)*

1. Choose **Add PDF** and pick the file.
2. Give it a clear **title**, a few **tags** (for example `tenma, power supply`) and an optional description.
3. Choose **Upload**.

The same PDF can't be added twice, and there is a size limit (50 MB by default). Use the pencil icon to correct
a title or tags later.

### Removing a document *(needs the "Manage the portal" permission)*

Use the bin icon. Deleting is permanent, so you are asked to confirm.

## Good to know

- Everything in the portal works **offline** — nothing is sent anywhere.
- Documents you add are kept with the station's data and **survive software updates**.
- Missing the **Portal** menu entry, or the **Add PDF** button? Your role doesn't include that permission — ask
  an administrator (see [Permissions](help:user-permissions)).
