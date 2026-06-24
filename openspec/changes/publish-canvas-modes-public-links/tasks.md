## 1. Prerequisite Alignment

- [ ] 1.1 Confirm `replace-viewer-with-public-publish-links` has landed or rebase this change onto its final public token APIs.
- [ ] 1.2 Record the final public browser route and public manifest/chart-data endpoint names used by the public-link change.
- [ ] 1.3 Remove or adjust any duplicated viewer/visibility tasks from this change after rebasing onto the public-link foundation.

## 2. Backend Manifest and Validation

- [ ] 2.1 Add shared backend constants for supported canvas format ids, canvas kinds, and fixed-size preset dimensions.
- [ ] 2.2 Extend publish request models to accept `canvas_format`, `viewport`, `nodes`, `edges`, and optional `web_design` payloads.
- [ ] 2.3 Add schema v2 published manifest models with `schema_version`, `canvas`, `content`, and `charts` sections.
- [ ] 2.4 Add read-time normalization for legacy schema v1 Web Page Design manifests.
- [ ] 2.5 Normalize published nodes through a whitelist of supported public node types and safe data fields.
- [ ] 2.6 Validate unknown canvas formats with HTTP 422 before snapshot creation.
- [ ] 2.7 Validate fixed-size node bounds against server-known page dimensions and return offending node ids on failure.
- [ ] 2.8 Compute and store free-layout content bounds for infinite canvas snapshots.

## 3. Backend Snapshot Writing and Public Reads

- [ ] 3.1 Update `SnapshotWriter.write()` to write schema v2 manifests for free-layout, fixed-size, and web-page snapshots.
- [ ] 3.2 Update chart extraction/storage so all chart nodes included in the active canvas produce spec/data files.
- [ ] 3.3 Preserve existing redaction, forbidden-column filtering, row caps, and `data_truncated` flags for every canvas kind.
- [ ] 3.4 Update publish response/history models to include `canvas_format_id` and `canvas_kind`.
- [ ] 3.5 Update public manifest reads to return normalized schema v2 manifests without exposing internal file paths.
- [ ] 3.6 Update public chart-data reads to work for charts referenced by free-layout and fixed-size node snapshots.

## 4. Frontend Publish Flow

- [ ] 4.1 Move public Publish access from `WebDesignCanvas` into a shared workspace-level control available in every supported canvas format.
- [ ] 4.2 Build a serializer that extracts only the active format's nodes/edges from the workspace store.
- [ ] 4.3 Extend the publish client to send `canvas_format`, `viewport`, active nodes/edges, optional `web_design`, and chart snapshots.
- [ ] 4.4 Keep Web Page Design chart-zone serialization compatible with the existing grid/sidebar/pages layout.
- [ ] 4.5 Add mode-specific publish blocking for empty active canvas, empty chart data, unsupported format, and fixed-size out-of-bounds nodes.
- [ ] 4.6 Update publish status/history UI to display the canvas mode for the latest published snapshot and history entries.

## 5. Public Frontend Rendering

- [ ] 5.1 Add published manifest TypeScript types for schema v2 canvas metadata and node/content snapshots.
- [ ] 5.2 Add a public renderer router that selects free-layout, fixed-size, or web-page rendering from `manifest.canvas.kind`.
- [ ] 5.3 Implement `PublishedFreeCanvas` with read-only node rendering, fit-to-content initial viewport, and snapshot chart loading.
- [ ] 5.4 Implement `PublishedFixedCanvas` with fixed page dimensions, responsive scale-to-fit behavior, and read-only node rendering.
- [ ] 5.5 Adapt the existing web-page public renderer to consume normalized schema v2 web-page manifests.
- [ ] 5.6 Ensure all public canvas renderers omit editor chrome, workspace navigation, collaborator controls, and publish/history controls.
- [ ] 5.7 Add neutral invalid/unavailable states for unsupported canvas kind, unsupported format id, invalid fixed dimensions, and revoked/unknown tokens.

## 6. Tests

- [ ] 6.1 Add backend unit tests for schema v2 manifest creation for infinite, fixed-size, and web-page snapshots.
- [ ] 6.2 Add backend validation tests for unsupported format ids and fixed-size out-of-bounds nodes.
- [ ] 6.3 Add backend tests proving legacy schema v1 Web Page Design manifests normalize to `canvas.kind: "web_page"`.
- [ ] 6.4 Add backend public-read tests proving manifest/chart-data responses omit private workspace state and internal paths.
- [ ] 6.5 Add frontend unit tests for active-format publish serialization.
- [ ] 6.6 Add frontend tests for public renderer selection by `canvas.kind`.
- [ ] 6.7 Add frontend rendering tests for free-layout and fixed-size public canvases.
- [ ] 6.8 Update Web Page Design publish tests to assert it still publishes through the unified manifest contract.
- [ ] 6.9 Add regression tests that a stable public token can update from web-page to fixed-size to infinite canvas.

## 7. Cleanup and Verification

- [ ] 7.1 Remove obsolete Web Design-only publish assumptions from i18n keys, frontend copy, and helper names.
- [ ] 7.2 Update developer docs or `.env.example` only if this change introduces new public route/base-url configuration.
- [ ] 7.3 Run targeted backend tests for publish, public read, manifest normalization, and published-page security.
- [ ] 7.4 Run targeted frontend Vitest coverage for publish serialization and public canvas renderers.
- [ ] 7.5 Run `openspec status --change publish-canvas-modes-public-links` and any repository OpenSpec validation command before implementation is considered ready.
