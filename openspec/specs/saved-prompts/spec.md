# saved-prompts Specification

## Purpose
TBD - created by archiving change add-saved-prompts. Update Purpose after archive.
## Requirements
### Requirement: Users can manage private saved prompts
The system SHALL allow an authenticated user to create, list, search, retrieve, update, and archive saved prompts owned by that user. Saved prompts MUST include a stable ID, name, prompt body, extracted variables, optional capability hints, usage metadata, creation timestamp, update timestamp, and archive state. The system MUST NOT expose one user's saved prompts to any other user.

#### Scenario: Create prompt extracts variables
- **WHEN** an authenticated user creates a saved prompt named "Travel vaccine" with body "What is the travel vaccine recommendation for {country}"
- **THEN** the system stores the prompt under that user's identity
- **AND** the response includes a stable prompt ID
- **AND** the response includes variables `["country"]`
- **AND** the prompt is returned by subsequent list calls for that same user

#### Scenario: Search returns only active owner prompts
- **WHEN** a user lists saved prompts with query "travel"
- **THEN** the system returns only that user's non-archived prompts whose name or body matches the query
- **AND** archived prompts are excluded unless the request explicitly includes archived prompts
- **AND** results are ordered by most recently used, then most recently updated

#### Scenario: User isolation is enforced
- **WHEN** user A has created a saved prompt
- **AND** user B requests, updates, deletes, or uses that prompt ID
- **THEN** the system responds as if the prompt does not exist or denies access
- **AND** user B receives no prompt body, name, variables, or capability metadata from user A's prompt

#### Scenario: Update recalculates variables
- **WHEN** a user updates a saved prompt body from "Analyze {department}" to "Analyze {department} for {month}"
- **THEN** the system persists the new body
- **AND** the response variables are `["department", "month"]`
- **AND** the prompt `updated_at` value changes

#### Scenario: Archive hides prompt from normal list
- **WHEN** a user archives a saved prompt
- **THEN** the prompt no longer appears in the default saved prompt list
- **AND** direct use of that prompt is rejected
- **AND** the archived record remains available for explicit archived listing or future migration cleanup

### Requirement: Saved prompt validation is enforced
The system SHALL validate saved prompt input on both client and server. A saved prompt MUST have a non-empty name and non-empty body. Variable placeholders MUST use the single-brace syntax `{variable_name}` with names matching `[A-Za-z][A-Za-z0-9_]{0,63}`. Repeated exact variables are allowed and rendered from a single value; placeholders that differ only by case MUST be rejected as ambiguous. Literal braces MUST be representable by escaping them with backslashes.

#### Scenario: Save disabled for missing required fields
- **WHEN** the create or edit prompt form has an empty name or empty body
- **THEN** the save action is disabled in the UI
- **AND** the API rejects the same payload if submitted directly

#### Scenario: Invalid variable placeholder is rejected
- **WHEN** a user attempts to save a prompt containing "Compare {2026_month}"
- **THEN** the system rejects the prompt with a validation error identifying the invalid placeholder
- **AND** the prompt is not created or updated

#### Scenario: Duplicate exact variable creates one field
- **WHEN** a user saves "Compare {department} headcount with {department} attrition"
- **THEN** the prompt is accepted
- **AND** the stored variables list contains only `["department"]`

#### Scenario: Ambiguous variable casing is rejected
- **WHEN** a user attempts to save "Compare {Department} with {department}"
- **THEN** the system rejects the prompt as ambiguous
- **AND** the prompt is not created or updated

#### Scenario: Escaped braces are not variables
- **WHEN** a user saves "Return JSON like \{\"department\": \"{department}\"\}"
- **THEN** the escaped JSON braces are stored as literal braces
- **AND** the stored variables list contains only `["department"]`

### Requirement: Chat composer exposes saved prompts from the action menu
The Designer chat composer SHALL expose saved prompts through the existing "+" action menu. The menu MUST include a "Saved prompts" entry with access to "Create prompt", "Manage prompts", and selectable saved prompt rows. Selecting create or manage MUST keep the current composer draft intact. Prompt insertion MUST never auto-send the chat message.

#### Scenario: Create prompt opens from the action menu
- **WHEN** a user opens the chat composer "+" menu and selects "Saved prompts" then "Create prompt"
- **THEN** the create prompt modal opens
- **AND** the current composer text, selected file, chart type, and generation options remain unchanged

#### Scenario: Manage prompts opens from the action menu
- **WHEN** a user opens the chat composer "+" menu and selects "Saved prompts" then "Manage prompts"
- **THEN** the saved prompts management surface opens
- **AND** the user can search, create, edit, delete, and insert prompts from that surface

#### Scenario: Prompt without variables inserts at caret
- **WHEN** the composer contains "Please " with the caret at the end
- **AND** the user selects a saved prompt whose body is "summarize this table"
- **THEN** the composer becomes "Please summarize this table"
- **AND** focus returns to the composer
- **AND** no chat message is sent

#### Scenario: Prompt with selected text replaces selection
- **WHEN** the composer contains "Analyze old text now" with "old text" selected
- **AND** the user selects a saved prompt whose body is "turnover by department"
- **THEN** the selected text is replaced by "turnover by department"
- **AND** the surrounding composer text is preserved

### Requirement: Historical user prompts can be saved or copied from chat bubbles
The Designer chat history SHALL expose compact actions on user-authored message bubbles. These actions MUST appear only when the user message row is hovered or receives keyboard focus. The actions MUST include saving the message text as a saved prompt template through a prefilled create flow and copying the exact message text to the clipboard. The system MUST NOT show these actions on assistant, system, agent trace, chart, or ingestion-control messages.

#### Scenario: Save historical user prompt opens prefilled create flow
- **WHEN** a user hovers over a historical user chat bubble containing "Show attrition by department"
- **AND** the user selects the save-as-prompt action
- **THEN** the create prompt dialog opens
- **AND** the prompt body field is prefilled with "Show attrition by department"
- **AND** the prompt name field is prefilled with an editable name derived from the message text
- **AND** the prompt is saved through the same validation and API path as composer-created saved prompts

#### Scenario: Copy historical user prompt copies exact text
- **WHEN** a user hovers over a historical user chat bubble containing "Compare HR and PM turnover"
- **AND** the user selects the copy prompt action
- **THEN** the exact message text "Compare HR and PM turnover" is copied to the clipboard
- **AND** the UI reports whether the copy succeeded or failed

#### Scenario: Assistant messages do not expose prompt actions
- **WHEN** an assistant message, chart card, agent trace, or ingestion confirmation is rendered
- **THEN** save-as-prompt and copy-prompt actions are not shown for that generated content

### Requirement: Variable prompts collect values before insertion
The system SHALL collect values for saved prompts that contain variables before inserting the rendered prompt into the composer. The variable-fill UI MUST show one input per unique variable in stored order, require values for every variable, and render every occurrence of the variable with the supplied value. Variable values are transient and MUST NOT be persisted into the saved prompt body.

#### Scenario: Variable fill dialog opens
- **WHEN** a user selects a saved prompt containing variables `["department", "month"]`
- **THEN** the system opens a variable-fill dialog with fields for `department` and `month`
- **AND** the composer text is unchanged until the user confirms insertion

#### Scenario: Confirming variables renders prompt
- **WHEN** a saved prompt body is "Analyze {department} attrition in {month}"
- **AND** the user enters "Sales" for `department` and "May 2026" for `month`
- **THEN** the inserted composer text contains "Analyze Sales attrition in May 2026"
- **AND** the saved prompt template remains "Analyze {department} attrition in {month}"

#### Scenario: Required variable value missing
- **WHEN** the variable-fill dialog has an empty value for any variable
- **THEN** the insert action is disabled
- **AND** no prompt text is inserted into the composer

#### Scenario: Cancelling variables preserves draft
- **WHEN** a user opens the variable-fill dialog and cancels it
- **THEN** the dialog closes
- **AND** the composer draft remains exactly as it was before the saved prompt was selected

### Requirement: Capability hints integrate with composer options without granting privileges
Saved prompts SHALL support optional capability hints from a controlled allowlist. Applying a prompt MAY preselect matching frontend composer options, but capability hints MUST NOT grant backend permissions, bypass agent guardrails, or execute any tool by themselves.

#### Scenario: Capability hints are stored and returned
- **WHEN** a user creates a prompt with capability hints `["multi_chart", "data_labels"]`
- **THEN** the system persists those hints
- **AND** list and retrieve responses return those hints for the owning user

#### Scenario: Unsupported capability hint is rejected
- **WHEN** a user submits a prompt with capability hint `"raw_execute_sql"`
- **THEN** the system rejects the request as invalid
- **AND** the prompt is not created or updated

#### Scenario: Applying hint preselects composer option only
- **WHEN** a user inserts a saved prompt with the `multi_chart` capability hint
- **THEN** the multi-chart composer option is selected if available
- **AND** no backend tool call is made until the user explicitly sends the chat message

### Requirement: Saved prompt management UI supports search and actions
The system SHALL provide a management surface for saved prompts reachable from the composer. The surface MUST include a create action, search input, list rows with name and body preview, edit action, archive/delete action, insert action, loading state, error state, and empty state.

#### Scenario: Empty state offers creation
- **WHEN** a user opens the management surface with no active saved prompts
- **THEN** the system displays an empty state
- **AND** the user can open the create prompt modal from that state

#### Scenario: Search filters prompt list
- **WHEN** a user searches for "attrition" in the management surface
- **THEN** the list displays only matching active prompts returned by the backend
- **AND** clearing the search restores the active prompt list

#### Scenario: Edit from management updates row
- **WHEN** a user edits a prompt name or body from the management surface
- **THEN** the updated row appears without requiring a page reload
- **AND** the backend value matches the edited values

#### Scenario: Delete from management removes row
- **WHEN** a user confirms deleting a prompt from the management surface
- **THEN** the row is removed from the active list
- **AND** the prompt is archived in the backend

### Requirement: Prompt lifecycle audit excludes prompt content
The system SHALL emit audit events for saved prompt create, update, archive/delete, and use actions. Audit event details MUST NOT contain prompt names, prompt bodies, rendered prompt text, or variable values.

#### Scenario: Create audit omits body
- **WHEN** a user creates a saved prompt
- **THEN** an audit event is written with action `saved_prompt_create`
- **AND** the event includes prompt ID, actor ID, variable count, and capability IDs
- **AND** the event does not include the prompt name or body

#### Scenario: Use audit omits rendered values
- **WHEN** a user inserts a variable saved prompt with runtime values
- **THEN** an audit event is written with action `saved_prompt_use`
- **AND** the event does not include variable values or rendered prompt text

