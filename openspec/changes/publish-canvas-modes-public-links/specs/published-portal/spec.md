## MODIFIED Requirements

### Requirement: Published page renders with page-level sidebar and chart grid
When a public published page is loaded, the system SHALL inspect the published manifest canvas metadata and render the matching read-only canvas experience:
- Web Page Design snapshots render the page-level sidebar and chart grid.
- Free Layout snapshots render the infinite canvas content in a read-only fit-to-content surface.
- Fixed Size snapshots render the saved page frame and content in a read-only page viewer.

All chart content SHALL load from published snapshot chart files through public chart-data routes. The page MUST NOT query the live workspace, live DuckDB session, or authenticated editor APIs.

#### Scenario: Web-page sidebar navigation
- **WHEN** the public manifest has `canvas.kind: "web_page"` and the user clicks a sidebar section
- **THEN** the grid scrolls or switches to the linked published page/row using the snapshot sidebar data

#### Scenario: Web-page charts load from snapshot
- **WHEN** a Web Page Design published page is rendered
- **THEN** each chart zone fetches its spec and data from the public snapshot chart-data endpoint and renders using the same chart strategy as the editor preview

#### Scenario: Web-page text zones render formatted text
- **WHEN** a Web Page Design zone contains a text block
- **THEN** the text is rendered from the published snapshot with its saved style

#### Scenario: Free-layout page renders without sidebar
- **WHEN** the public manifest has `canvas.kind: "free_layout"`
- **THEN** the public page renders the free-layout canvas surface and does not render the Web Page Design sidebar

#### Scenario: Fixed-size page renders without sidebar
- **WHEN** the public manifest has `canvas.kind: "fixed_size"`
- **THEN** the public page renders the fixed page viewer and does not render the Web Page Design sidebar unless a later fixed-page navigation model is explicitly added

## ADDED Requirements

### Requirement: Public page route supports canvas-mode refresh
The public page route SHALL keep the same token URL when a workspace is republished from a different canvas mode, and SHALL render the newest active snapshot according to that snapshot's canvas kind.

#### Scenario: Token changes from web page to A4 snapshot
- **WHEN** a designer first publishes a workspace from Web Page Design and later updates the same public link from an A4 canvas
- **THEN** the existing public token URL renders the A4 fixed-size snapshot after the update

#### Scenario: Token changes from A4 snapshot to infinite canvas
- **WHEN** a designer republishes the active public link from the infinite canvas after previously publishing A4
- **THEN** the existing public token URL renders the free-layout snapshot after the update

### Requirement: Invalid canvas manifest fails closed
The public page route SHALL render a neutral invalid-link or unavailable-page state when a resolved manifest has an unsupported `canvas.kind`, unsupported `canvas.format_id`, or invalid mode-specific layout.

#### Scenario: Unsupported canvas kind
- **WHEN** a public token resolves to a manifest with an unsupported `canvas.kind`
- **THEN** the visitor sees the public unavailable-page state and no private manifest details are exposed

#### Scenario: Invalid fixed-size layout
- **WHEN** a public token resolves to a fixed-size manifest without valid page dimensions
- **THEN** the visitor sees the public unavailable-page state and no editor stack trace is exposed

### Requirement: Public canvas renderers hide editor-only UI
Every public canvas renderer SHALL omit editor-only controls including node drag handles, resize handles, selection outlines, chart replacement actions, canvas format switchers, export buttons, collaborator/share management, and workspace sidebars.

#### Scenario: Free-layout editor UI omitted
- **WHEN** a visitor opens a public free-layout canvas
- **THEN** the page contains no edit toolbar, minimap edit controls, node delete controls, drag handles, or resize handles

#### Scenario: Fixed-size editor UI omitted
- **WHEN** a visitor opens a public fixed-size canvas
- **THEN** the page contains no canvas format selector, export dropdown, node edit controls, or React Flow editor controls

#### Scenario: Web-page editor UI omitted
- **WHEN** a visitor opens a public web-page snapshot
- **THEN** the page contains no grid editing handles, sidebar editor, publish button, history panel, share/collaborator button, or workspace navigation
