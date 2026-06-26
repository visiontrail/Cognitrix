## Why

After `replace-viewer-with-public-publish-links`, public publishing will be defined as a stable unauthenticated link to a read-only snapshot. The current product scope still treats Web Page Design as the only publishable canvas surface, which leaves Free Layout / infinite canvas and Fixed Size / A4-style canvases outside the public-link model.

This change makes public links a canvas-level capability: any supported workspace canvas mode can be snapshotted, published, opened by public token, and rendered faithfully without requiring live workspace access.

## What Changes

- Extend the publish contract so a workspace publish request carries a `canvas_mode` and mode-specific layout snapshot instead of assuming Web Page Design.
- Support public-link snapshots for:
  - Free Layout / infinite React Flow canvas, preserving node positions, viewport bounds, chart assets, text nodes, and z-order.
  - Fixed Size canvases such as A4 pages, preserving page size, orientation, margins, scale, and page ordering where applicable.
  - Web Page Design, preserving the existing section-grid/sidebar snapshot behavior.
- Add a shared published snapshot manifest envelope that identifies the canvas kind and lets public readers choose the correct renderer.
- Add standalone public rendering for non-webpage canvases on the public token route introduced by `replace-viewer-with-public-publish-links`.
- Keep publish lifecycle semantics unchanged: owner/editor-only management, one stable active public link per workspace, refresh-in-place updates, immediate revoke, snapshot-only reads, and publish-time redaction/row caps.
- Preserve the editor experience by allowing Publish from every supported canvas mode while showing mode-appropriate validation and preview/open-link behavior.
- Do not add public editing, public chat/querying, per-user visibility, password links, or live DuckDB reads.

## Capabilities

### New Capabilities

- `published-canvas-rendering`: Defines how public pages resolve and render mode-specific published canvas snapshots for Free Layout, Fixed Size/A4, and Web Page Design canvases.

### Modified Capabilities

- `workspace-publish`: Publish requirements change from Web Page Design-only snapshots to a canvas-mode-aware snapshot contract shared by all supported workspace canvas modes.
- `published-portal`: Public published-page rendering must choose the correct read-only renderer by snapshot canvas kind instead of assuming a web-page/sidebar layout.
- `canvas-web-design-mode`: Web Page Design remains one publishable canvas mode, but its publish requirements become one branch of the unified canvas publishing model rather than the sole public-link surface.

## Impact

- Backend:
  - `apps/api/workspaces.py` publish endpoints need mode-aware request/response models and validation.
  - `apps/api/published_pages.py` needs a versioned manifest envelope and mode-specific snapshot writers/readers.
  - Public token routes from `replace-viewer-with-public-publish-links` need to return mode-aware manifests and static chart/text asset data for every supported canvas mode.
  - Snapshot storage under `UPLOAD_DIR/published/{workspace_id}/{version}/` needs a stable layout for Free Layout and Fixed Size assets alongside the existing chart specs/data.
- Frontend:
  - Workspace canvas state and Publish UI need to serialize the active canvas mode and layout payload.
  - The public route, such as `/p/[token]`, needs renderer selection for infinite canvas, fixed-size/A4 canvas, and web-page design snapshots.
  - Existing chart/text rendering components should be reused in read-only mode where possible.
- Data and compatibility:
  - New manifests must be versioned so old web-page snapshots can still be read or migrated.
  - No public route may expose workspace membership, edit controls, internal file paths, or live session identifiers.
- Tests:
  - Add backend snapshot contract tests for each canvas mode.
  - Add frontend rendering tests for public infinite canvas, A4/fixed-size canvas, and web-page snapshots.
  - Add regression tests that public-link update/revoke behavior remains identical across canvas modes.
