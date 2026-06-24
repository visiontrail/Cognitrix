## Context

Cognitrix already stores multiple workspace canvas formats in the frontend state model. The active format is `canvasFormat.id`, and per-format nodes/edges live in `nodesByFormat` and `edgesByFormat`. Current publishing, however, is wired from `WebDesignCanvas` only: `publishWorkspace()` serializes `webDesign` grid/sidebar state plus chart rows, and the portal renderer assumes a web-page grid with a page sidebar.

The intended preceding change, `replace-viewer-with-public-publish-links`, replaces viewer/portal visibility with one stable public link per workspace. This design builds on that lifecycle. It does not redefine token creation, revocation, or owner/editor authorization; it makes the published snapshot behind that token canvas-mode-aware.

## Goals / Non-Goals

**Goals:**

- Publish the active workspace canvas format through the same public-link lifecycle used for Web Page Design.
- Preserve layout fidelity for Free Layout / infinite canvases and Fixed Size canvases such as A4 portrait/landscape.
- Keep published pages read-only, snapshot-only, and independent from live DuckDB sessions.
- Reuse existing chart/text rendering primitives where practical.
- Keep chart data redaction, row caps, and immutable version history unchanged.
- Version the manifest format so older Web Page Design snapshots can still be served.

**Non-Goals:**

- Public editing, commenting, or remixing of published canvases.
- Public chart chat/querying for non-webpage canvases.
- Password-protected links, expiring links, per-user visibility, or allowlists.
- Raster-only publishing as the primary format.
- Publishing every saved canvas format at once; this change publishes the currently active canvas format.

## Decisions

### Decision 1: Use a versioned manifest envelope with canvas metadata

Published snapshots SHALL use a top-level manifest envelope that identifies both the schema version and the canvas mode:

```json
{
  "schema_version": 2,
  "workspace_id": "workspace-id",
  "version": 3,
  "published_at": "2026-06-24T00:00:00+00:00",
  "canvas": {
    "format_id": "a4-portrait",
    "kind": "fixed_size",
    "viewport": { "x": 0, "y": 0, "zoom": 1 },
    "page": { "width": 794, "height": 1123, "preset_id": "a4-portrait" }
  },
  "content": {
    "nodes": [],
    "edges": []
  },
  "charts": []
}
```

`canvas.format_id` mirrors the existing frontend `WorkspaceCanvasFormatId`. `canvas.kind` is a coarse renderer selector: `free_layout`, `fixed_size`, or `web_page`.

Alternative considered: infer renderer type from old fields such as `layout` and `sidebar`. Rejected because it keeps Web Page Design as the implicit default and makes future formats ambiguous.

### Decision 2: Publish a declarative canvas snapshot, not a screenshot

Free Layout and Fixed Size canvases SHALL publish sanitized node and edge JSON plus chart spec/data references. The public page renderer reconstructs the read-only canvas from that data.

This keeps text selectable, charts rendered through `ChartPreview`, and chart rows governed by the existing snapshot data files. A screenshot can remain an optional thumbnail/export artifact, but it is not the canonical public representation.

Alternative considered: publish PNG/PDF output from `canvas-export.ts`. Rejected because it loses chart semantics, blocks responsive rendering, duplicates redaction responsibility into a browser capture path, and makes chart data unavailable to the existing published chart renderer.

### Decision 3: Backend validates mode-specific layout instead of trusting the client

The publish request SHALL include:

- `canvas_format`: the active format id;
- `viewport`: the React Flow viewport for free/fixed canvases;
- `nodes` / `edges`: the active format's serialized nodes and edges;
- `web_design`: the existing grid/sidebar/pages payload only when `canvas_format.id = "web-design"`;
- `charts`: extracted chart snapshots for chart nodes included in the active canvas.

The backend validates format ids against a small shared allowlist that matches `CANVAS_FORMAT_PRESETS`. For fixed-size formats, the backend derives width/height from the preset instead of accepting arbitrary page dimensions from the client.

Alternative considered: let the frontend send any width/height and treat it as a custom paper size. Rejected for this change because it expands product scope and creates avoidable renderer/security validation work.

### Decision 4: Fixed-size publish is strict about page bounds

For fixed-size formats, any visible node whose bounding box extends outside the page frame SHALL block publishing with a structured validation error. The public renderer clips to the page frame as a last defense, but users should not publish a page that silently drops content.

Alternative considered: allow out-of-bounds content and clip it. Rejected because A4/letter publishing is used as a document-like surface where silent clipping looks like data loss.

### Decision 5: Public renderer selection happens in one public route

The public route introduced by the public-link change, such as `/p/[token]`, SHALL fetch the token manifest, inspect `manifest.canvas.kind`, and choose:

- `PublishedFreeCanvas` for `free_layout`;
- `PublishedFixedCanvas` for `fixed_size`;
- the existing web page/grid renderer for `web_page`.

All three renderers use unauthenticated public token APIs for chart data. None render edit controls, workspace navigation, collaborator UI, or authenticated portal browsing.

Alternative considered: create separate routes per canvas type. Rejected because the public link should remain stable when a designer republishes the workspace from a different canvas mode.

### Decision 6: Legacy Web Page Design manifests are adapted at read time

Existing manifests without `schema_version` SHALL be treated as schema v1 Web Page Design snapshots. The backend public manifest response can wrap them in a v2 envelope or the frontend can normalize them after fetch; prefer backend normalization so all public clients receive one contract.

Alternative considered: migrate every snapshot file on disk. Rejected because immutable published versions should remain untouched when a read-time compatibility layer is enough.

## Risks / Trade-offs

- Fixed-size publish blocks users with off-page content -> show the offending node titles/ids in owner-side validation and provide a "fit to page" follow-up action separately.
- Free Layout canvases can be very large -> store bounds in the manifest, fit the initial viewport to bounds, and cap public zoom/pan rendering work.
- React Flow editor nodes may contain UI-only fields -> normalize nodes through a whitelist before writing the manifest.
- Public route may accidentally expose internal workspace state -> exclude `workspace_id` from frontend-visible owner details where not needed, omit live session ids, and never expose filesystem paths.
- Adding a generic manifest can collide with the in-flight public-link change -> implement this only after `replace-viewer-with-public-publish-links` lands, then rebase the API names to its final token route/status response.

## Migration Plan

1. Land `replace-viewer-with-public-publish-links` so the public token lifecycle and unauthenticated public read route exist.
2. Add schema v2 manifest models and read-time normalization for schema v1 Web Page Design manifests.
3. Extend publish request parsing to accept `canvas_format`, `viewport`, `nodes`, `edges`, and optional `web_design`.
4. Add mode-specific snapshot validation and writing in `published_pages.py`.
5. Move Publish UI from `WebDesignCanvas` into the shared workspace toolbar/dialog, while keeping Web Page Design-specific validation available when that mode is active.
6. Add public renderer components for free and fixed canvases, then switch the public page route to select by `canvas.kind`.
7. Add targeted backend and frontend tests for each supported canvas mode.

Rollback keeps the public-link lifecycle intact: disable non-web publish UI, continue reading schema v1 Web Page Design manifests, and ignore schema v2 snapshots for new publishes until the renderer is restored.

## Open Questions

- Whether fixed-size public pages should support multi-page output in the first implementation or treat each fixed canvas preset as one page.
- Whether public infinite canvas should expose minimap/zoom controls or only fit-to-content plus browser scrolling.
- Whether `section` nodes should continue to be supported as read-only public nodes, or be migrated to text/heading nodes before publish.
