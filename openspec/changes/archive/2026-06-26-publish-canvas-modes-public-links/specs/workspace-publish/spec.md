## MODIFIED Requirements

### Requirement: Publish action available on Web Page Design canvas
A **Publish** button SHALL be available to users whose role on the current workspace is `owner` or `editor` when the active canvas format is `infinite`, `web-design`, or any supported fixed-size preset. For users who are not owner/editor workspace collaborators, the Publish button MUST NOT render. Clicking the button opens the public-link publish dialog defined by the public publish-link capability rather than triggering an immediate publish.

The button SHALL be disabled when the active canvas contains no publishable content or when the active canvas fails mode-specific publish validation.

#### Scenario: Publish button visible to owner/editor
- **WHEN** a workspace owner or editor opens any supported canvas format
- **THEN** the toolbar renders the Publish button

#### Scenario: Publish button hidden for non-editors
- **WHEN** a user without owner/editor access opens any workspace canvas
- **THEN** the Publish button does not render

#### Scenario: Publish blocked with empty chart
- **WHEN** the active canvas contains a chart node or chart zone whose chart has no loaded data
- **THEN** the Publish button is disabled and the user is told that all charts must have data before publishing

#### Scenario: Publish blocked with no content
- **WHEN** the active canvas contains no chart, text, sticky note, divider, section, or web-page text-zone content
- **THEN** the Publish button is disabled

#### Scenario: Publish opens public-link dialog
- **WHEN** an owner/editor clicks the enabled Publish button
- **THEN** the system opens the public-link publish dialog and does not immediately create a snapshot

### Requirement: Publish creates an immutable versioned snapshot
When the user confirms publish in the public-link publish dialog, the system SHALL call `POST /workspaces/{workspace_id}/publish` with the active canvas format and mode-specific snapshot payload. The backend creates a new version record and writes the snapshot to `UPLOAD_DIR/published/{workspace_id}/{version}/`.

The snapshot SHALL contain:
- `manifest.json` with a versioned manifest envelope, canvas metadata, and mode-specific layout/content;
- `charts/{chart_id}/spec.json` for every published chart;
- `charts/{chart_id}/data.json` for every published chart's redacted and capped rows.

The raw data rows MUST pass through the same `redact_rows()` and `forbidden_sensitive_columns()` pipeline as the query runtime before being written. Public publish-link state points to the newest immutable version after a successful publish/update.

#### Scenario: Successful infinite canvas publish
- **WHEN** an owner/editor confirms publish while the active canvas format is `infinite`
- **THEN** the backend creates a new immutable snapshot whose manifest includes the free-layout nodes, edges, viewport metadata, content bounds, chart entries, and public canvas metadata

#### Scenario: Successful fixed-size publish
- **WHEN** an owner/editor confirms publish while the active canvas format is a supported fixed-size preset
- **THEN** the backend creates a new immutable snapshot whose manifest includes the fixed page preset, page dimensions, nodes, edges, chart entries, and public canvas metadata

#### Scenario: Successful web-page publish
- **WHEN** an owner/editor confirms publish while the active canvas format is `web-design`
- **THEN** the backend creates a new immutable snapshot whose manifest includes the web-page grid layout, pages, sidebar, text zones, chart zones, chart entries, and public canvas metadata

#### Scenario: Sensitive column redaction
- **WHEN** any published chart's underlying data contains columns flagged by `forbidden_sensitive_columns()` for the publishing user's role
- **THEN** those columns are excluded from `charts/{chart_id}/data.json`

#### Scenario: Data cap enforcement
- **WHEN** any published chart's source query returns more rows than `AGENT_MAX_SQL_ROWS`
- **THEN** only the first `AGENT_MAX_SQL_ROWS` rows are written to `data.json`; the manifest records `data_truncated: true` for that chart

## ADDED Requirements

### Requirement: Publish request carries active canvas snapshot
The publish request SHALL include the active canvas format id and only the active format's publishable snapshot. The request MUST NOT publish every saved format in `nodesByFormat` at once.

#### Scenario: Active infinite format serialized
- **WHEN** the active canvas format is `infinite`
- **THEN** the frontend sends `canvas_format.id: "infinite"`, the active free-layout nodes, active edges, viewport, and chart snapshots for chart nodes on that canvas

#### Scenario: Active fixed-size format serialized
- **WHEN** the active canvas format is `a4-portrait`, `a4-landscape`, `a3-portrait`, `letter-portrait`, or `wide-16-9`
- **THEN** the frontend sends that active format id, the active fixed-canvas nodes, active edges, viewport, and chart snapshots for chart nodes on that page

#### Scenario: Active web-design format serialized
- **WHEN** the active canvas format is `web-design`
- **THEN** the frontend sends `canvas_format.id: "web-design"`, the web-design layout/sidebar/pages payload, and chart snapshots for chart zones referenced by the active web-design layout

### Requirement: Backend validates supported canvas formats
The backend SHALL validate the submitted canvas format against the supported preset list. For fixed-size formats, the backend SHALL derive page dimensions from the known preset id rather than trusting client-supplied dimensions.

#### Scenario: Unsupported format rejected
- **WHEN** a publish request submits an unknown `canvas_format.id`
- **THEN** the backend returns HTTP 422 and does not create a snapshot or refresh the public link

#### Scenario: Fixed-size dimensions derived server-side
- **WHEN** a publish request submits `canvas_format.id: "a4-portrait"`
- **THEN** the snapshot manifest uses the server-known A4 portrait dimensions even if the request includes different dimensions

### Requirement: Fixed-size publish validates page bounds
For fixed-size canvas formats, publishing SHALL be blocked when any visible node's bounding box extends outside the fixed page frame.

#### Scenario: Fixed-size node outside page
- **WHEN** an owner/editor attempts to publish an A4 canvas containing a node that extends beyond the page frame
- **THEN** the backend returns HTTP 422 with the offending node ids and no snapshot is created

#### Scenario: Fixed-size nodes inside page
- **WHEN** all visible nodes are fully inside the fixed page frame
- **THEN** fixed-size publish validation passes

### Requirement: Publish history exposes canvas mode
Authenticated owner/editor publish history SHALL include the canvas format id and canvas kind for each published version.

#### Scenario: History shows canvas metadata
- **WHEN** an owner/editor calls `GET /workspaces/{workspace_id}/published`
- **THEN** each history item includes `canvas_format_id` and `canvas_kind` for that immutable version
