## 1. Backend permissions and prompt model

- [ ] 1.1 Add `prompts:read` and `prompts:write` permissions to `apps/api/auth.py` for roles that can access chat.
- [ ] 1.2 Create `apps/api/saved_prompts.py` with Pydantic request/response models for prompt create, update, list, retrieve, archive, and use responses.
- [ ] 1.3 Implement a reusable variable parser that extracts `{variable_name}` placeholders in first-seen order, supports escaped braces, ignores `{{...}}`, rejects malformed placeholders, and detects case-ambiguous duplicates.
- [ ] 1.4 Define a controlled capability-hint allowlist matching initial composer options (`multi_chart`, `data_labels`, and any file-upload hint selected for the UI).
- [ ] 1.5 Add timestamp and JSON serialization helpers for variables/capability hints following existing SQLite store conventions.

## 2. Backend storage and API

- [ ] 2.1 Implement a SQLite-backed `SavedPromptStore` under `UPLOAD_DIR/state/saved_prompts.sqlite3` with table/index creation on first use.
- [ ] 2.2 Implement store methods for owner-scoped create, list/search, get, update, archive, and mark-used operations.
- [ ] 2.3 Enforce active prompt-name uniqueness per owner, returning a clear validation error on duplicates.
- [ ] 2.4 Add `GET /saved-prompts`, `POST /saved-prompts`, `GET /saved-prompts/{prompt_id}`, `PATCH /saved-prompts/{prompt_id}`, `DELETE /saved-prompts/{prompt_id}`, and `POST /saved-prompts/{prompt_id}/use`.
- [ ] 2.5 Mount the saved prompts router from `apps/api/main.py`.
- [ ] 2.6 Ensure every route filters by `identity.user_id` and never accepts client-provided owner IDs.
- [ ] 2.7 Emit metadata-only audit events for create, update, archive/delete, and use.

## 3. Backend tests

- [ ] 3.1 Add unit tests for the variable parser: valid variables, repeated variables, case ambiguity, malformed names, escaped braces, and double braces.
- [ ] 3.2 Add unit tests for `SavedPromptStore` CRUD, search ordering, archive behavior, uniqueness, and mark-used metadata.
- [ ] 3.3 Add API tests for prompt create/list/get/update/delete/use happy paths.
- [ ] 3.4 Add security tests proving user B cannot read, update, archive, or use user A's prompt.
- [ ] 3.5 Add audit tests proving prompt names, bodies, rendered text, and variable values are absent from audit event details.

## 4. Frontend API, hooks, and shared helpers

- [ ] 4.1 Add `apps/web/lib/saved-prompts/types.ts` for prompt records, create/update payloads, variables, and capability hints.
- [ ] 4.2 Add `apps/web/lib/saved-prompts/api.ts` wrapping all `/saved-prompts` endpoints with existing auth-header patterns.
- [ ] 4.3 Add TanStack Query hooks for listing/searching prompts, create/update/archive mutations, and mark-used mutation with cache invalidation.
- [ ] 4.4 Add frontend helpers to render variable templates, insert text at textarea selection/caret with safe spacing, and map capability hints to composer generation options.
- [ ] 4.5 Add English and Chinese i18n strings for saved prompts menu rows, create/edit modal, variable-fill dialog, management view, errors, empty states, and aria labels.

## 5. Frontend composer integration

- [ ] 5.1 Refactor `apps/web/components/chat/chat-input.tsx` enough to delegate saved-prompt UI to child components while preserving existing file upload, chart type picker, column mention picker, and generation-option behavior.
- [ ] 5.2 Add a "Saved prompts" entry under the composer "+" menu with a keyboard-accessible submenu containing create, manage, and recent/matching prompt rows.
- [ ] 5.3 Implement `SavedPromptEditorDialog` for create/edit with name field, body textarea, live variable validation, optional capability selection, disabled save state, and server-error display.
- [ ] 5.4 Implement `SavedPromptVariableDialog` that shows one required field per stored variable and inserts rendered prompt text only after confirmation.
- [ ] 5.5 Implement `SavedPromptsManager` reachable from the composer menu with search, create, list rows, previews, edit, archive/delete confirm, insert action, loading, error, and empty states.
- [ ] 5.6 Wire prompt insertion to preserve the current composer draft, insert at the current selection/caret, restore focus, and never auto-send.
- [ ] 5.7 Wire capability hints so applying a prompt preselects matching generation options without making any backend call beyond mark-used.

## 6. Frontend tests

- [ ] 6.1 Add unit tests for template rendering, insertion-at-caret behavior, escaped braces, and capability-hint mapping helpers.
- [ ] 6.2 Add UI tests for opening create/manage from the "+" menu without mutating the composer draft.
- [ ] 6.3 Add UI tests for create/edit validation, including missing fields and invalid variables.
- [ ] 6.4 Add UI tests for inserting prompts with no variables, replacing selected text, and restoring composer focus.
- [ ] 6.5 Add UI tests for variable-fill confirmation/cancel behavior.
- [ ] 6.6 Add UI tests for management search, edit, archive/delete, empty state, and cache refresh after mutations.

## 7. Documentation and verification

- [ ] 7.1 Update repository documentation/AGENTS-relevant sections if needed to mention the saved prompts API and UI surface.
- [ ] 7.2 Run backend tests for saved prompts and related security/audit coverage.
- [ ] 7.3 Run relevant frontend Vitest suites for chat input and saved prompts.
- [ ] 7.4 Run `make lint` or the narrow backend/frontend lint commands needed for touched files.
- [ ] 7.5 Manually verify the composer menu flow in the browser: create prompt, insert static prompt, insert variable prompt, manage/search/edit/delete.
