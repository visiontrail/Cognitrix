## ADDED Requirements

### Requirement: Web Page Design publishes through unified canvas manifest
Web Page Design SHALL publish through the same canvas-mode-aware manifest envelope as other workspace canvas formats. Its existing grid, pages, sidebar, zones, text zones, and chart-zone behavior SHALL be preserved under `canvas.kind: "web_page"`.

#### Scenario: Web Design manifest includes canvas metadata
- **WHEN** a designer publishes while `canvasFormat.id` is `web-design`
- **THEN** the written manifest includes `schema_version: 2`, `canvas.format_id: "web-design"`, and `canvas.kind: "web_page"`

#### Scenario: Existing Web Design layout preserved
- **WHEN** a Web Page Design workspace with multiple pages, sidebar entries, chart zones, and text zones is published
- **THEN** the public manifest preserves the pages, sidebar linkage, chart-zone positions, text-zone content, and active page id needed by the web-page public renderer

### Requirement: Web Page Design publish validation remains mode-specific
Web Page Design SHALL keep its grid-specific publish validation while sharing the owner/editor authorization and public-link lifecycle used by every publishable canvas format.

#### Scenario: Empty Web Design chart zone blocks publish
- **WHEN** a Web Page Design page contains a chart zone whose referenced chart has no snapshot rows
- **THEN** publishing is blocked with the same chart-data-required validation used by the unified publish flow

#### Scenario: Web Design text-only page can publish
- **WHEN** a Web Page Design page contains text zones and no chart zones
- **THEN** publishing is allowed because the active canvas contains publishable content and no empty chart data requirement is violated

### Requirement: Web Page Design no longer owns the only Publish control
The Web Page Design toolbar SHALL NOT be the only place where Publish can be accessed. Publish availability SHALL be controlled by the shared workspace publish flow so Free Layout and Fixed Size canvases can publish through the same dialog and lifecycle.

#### Scenario: Web Design keeps Publish access
- **WHEN** an owner/editor opens Web Page Design
- **THEN** the user can still publish that Web Page Design snapshot

#### Scenario: Other canvas modes also publish
- **WHEN** an owner/editor switches from Web Page Design to an infinite or fixed-size canvas
- **THEN** the user can publish the active non-web canvas through the shared publish flow
