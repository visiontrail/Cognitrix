## ADDED Requirements

### Requirement: Published manifest identifies canvas renderer
Every public published canvas manifest SHALL include a versioned envelope with `schema_version`, `canvas.format_id`, and `canvas.kind`. `canvas.format_id` SHALL use one of the supported workspace canvas format ids. `canvas.kind` SHALL be one of `free_layout`, `fixed_size`, or `web_page`.

#### Scenario: Manifest for infinite canvas
- **WHEN** a workspace is published from the `infinite` canvas format
- **THEN** the public manifest includes `schema_version: 2`, `canvas.format_id: "infinite"`, and `canvas.kind: "free_layout"`

#### Scenario: Manifest for fixed-size canvas
- **WHEN** a workspace is published from an A4, A3, letter, or wide fixed-size canvas format
- **THEN** the public manifest includes `canvas.kind: "fixed_size"` and a `canvas.page` object with the preset width, height, and preset id

#### Scenario: Manifest for web page design
- **WHEN** a workspace is published from the `web-design` canvas format
- **THEN** the public manifest includes `canvas.format_id: "web-design"` and `canvas.kind: "web_page"`

### Requirement: Public renderer selected from canvas kind
The public page route SHALL select its read-only renderer from `manifest.canvas.kind`. The route MUST NOT require authentication, workspace membership, app mode, or editor state to decide which renderer to use.

#### Scenario: Infinite canvas public link
- **WHEN** a visitor opens a valid public token whose manifest has `canvas.kind: "free_layout"`
- **THEN** the page renders the free-layout canvas renderer with the snapshot nodes, edges, and chart references from the manifest

#### Scenario: Fixed-size public link
- **WHEN** a visitor opens a valid public token whose manifest has `canvas.kind: "fixed_size"`
- **THEN** the page renders the fixed-size canvas renderer using the manifest page dimensions

#### Scenario: Web page public link
- **WHEN** a visitor opens a valid public token whose manifest has `canvas.kind: "web_page"`
- **THEN** the page renders the web-page/grid renderer using the manifest layout and sidebar

### Requirement: Free-layout public canvas is read-only and fit to content
The free-layout public renderer SHALL render the published nodes and edges in their saved positions, fit the initial viewport to the published content bounds, and expose no editing controls.

#### Scenario: Free-layout nodes render in snapshot positions
- **WHEN** the public manifest contains chart, text, sticky note, divider, or section nodes with positions and dimensions
- **THEN** the public canvas renders those nodes at the saved positions and sizes without drag handles, resize handles, delete actions, or edit affordances

#### Scenario: Free-layout chart loads snapshot data
- **WHEN** a public chart node is rendered on the free-layout canvas
- **THEN** the chart loads its spec and rows from the public snapshot chart-data endpoint, not from the live workspace or DuckDB session

#### Scenario: Free-layout initial viewport
- **WHEN** the public free-layout canvas loads
- **THEN** the initial viewport fits all published nodes with padding instead of using the editor's last pan/zoom as the only visible area

### Requirement: Fixed-size public canvas preserves page frame
The fixed-size public renderer SHALL render a page frame with the published preset dimensions and place all snapshot nodes relative to that page coordinate system.

#### Scenario: A4 portrait page renders with preserved dimensions
- **WHEN** the public manifest has `canvas.format_id: "a4-portrait"` and `canvas.kind: "fixed_size"`
- **THEN** the public renderer displays a portrait page with the stored A4 pixel dimensions and places nodes at their saved coordinates

#### Scenario: Fixed page scales to viewport
- **WHEN** the browser viewport is narrower than the fixed page width
- **THEN** the public renderer scales the page down for viewing without mutating node coordinates in the snapshot

#### Scenario: Fixed page hides editor chrome
- **WHEN** a fixed-size public canvas renders
- **THEN** the page frame contains only published content and no React Flow minimap, controls, selection outlines, resize handles, or export/edit toolbar

### Requirement: Public canvas responses omit private workspace state
Public canvas manifest and chart-data responses SHALL omit workspace membership, owner identity, collaborator lists, live dataset/session identifiers, local filesystem paths, and auth-only URLs.

#### Scenario: Public manifest privacy
- **WHEN** a visitor fetches a public manifest for any canvas kind
- **THEN** the response includes only the data required to render the published snapshot and omits membership roles, collaborator details, and internal file paths

#### Scenario: Public chart privacy
- **WHEN** a visitor fetches public chart data for any canvas kind
- **THEN** the response contains the published chart spec and redacted/capped snapshot rows only

### Requirement: Legacy web-page snapshots are readable
Published manifests without `schema_version` SHALL be treated as legacy Web Page Design snapshots and normalized to the current public manifest contract before rendering.

#### Scenario: Legacy manifest opened by public link
- **WHEN** a public token resolves to an older manifest containing `layout`, `sidebar`, and `charts` but no `schema_version`
- **THEN** the public manifest response is interpreted as `canvas.kind: "web_page"` and the page renders with the web-page/grid renderer
