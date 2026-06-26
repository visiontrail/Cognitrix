## Context

Cognitrix has a durable user account model, JWT authorization, workspace-scoped chat state, and several SQLite-backed state stores under `UPLOAD_DIR/state/`. The Designer chat composer currently owns its "+" action menu inside `apps/web/components/chat/chat-input.tsx`; that menu supports file upload and selectable generation options, but there is no reusable prompt library.

The target UX mirrors the screenshots: "Saved prompts" appears under the composer "+" menu, offers "Create prompt" and "Manage prompts", lists saved prompts inline, and provides a creation modal with name, prompt body, `{variable}` placeholders, and optional capability/tool selection. Public OpenAI documentation for Playground prompt management uses reusable prompts with `{variables}`, and the broader ChatGPT/prompt-manager ecosystem emphasizes searchable libraries plus instant insertion; this design adopts those interaction patterns without depending on a third-party service.

Stakeholders:
- **Designer user**: wants to save high-value BI prompts and insert them into active chat turns quickly.
- **Admin/security**: needs prompt bodies scoped to the owning user and excluded from audit logs.
- **Frontend**: needs a keyboard-accessible composer menu, modal/editor flows, and variable insertion without destabilizing existing chat input behaviors.
- **Backend**: owns durability, user isolation, validation, and audit metadata.

## Goals / Non-Goals

**Goals:**
- Provide user-owned saved prompts that sync across browsers/devices.
- Support create, read/search, update, archive/delete, and use tracking.
- Extract and validate `{variable}` placeholders from prompt bodies.
- Insert prompts into the active composer without automatically sending the message.
- For variable prompts, collect values and render the final text before insertion.
- Let users reuse historical user chat turns by copying the prompt text or opening a save-as-template flow from the message bubble.
- Preserve existing chat, ingestion, and chart-generation behavior when saved prompts are unused.
- Keep prompt bodies private to the owning authenticated user and out of audit logs.

**Non-Goals:**
- Workspace/team prompt sharing, prompt folders, tags, marketplace publishing, or approval workflows.
- Prompt version history or rollback.
- Automatic prompt chaining or auto-send on selection.
- Backend execution of saved prompts as trusted/system instructions. Saved prompts remain ordinary user text.
- Import/export from ChatGPT, browser extensions, Notion, or other external libraries.

## Decisions

### 1. Store saved prompts server-side, scoped by `owner_user_id`

Create a backend store for saved prompts instead of keeping them only in `localStorage`. The store should follow existing repo patterns: a small SQLite-backed class plus an APIRouter. A dedicated `state/saved_prompts.sqlite3` is preferred because prompt storage is a separate product concern, but using the existing state DB is acceptable if the implementation follows the migration conventions already present in the repo.

Suggested table:
- `id TEXT PRIMARY KEY`
- `owner_user_id TEXT NOT NULL`
- `name TEXT NOT NULL`
- `body TEXT NOT NULL`
- `variables_json TEXT NOT NULL`
- `capabilities_json TEXT NOT NULL`
- `usage_count INTEGER NOT NULL DEFAULT 0`
- `last_used_at TEXT NULL`
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`
- `archived_at TEXT NULL`

Add an index on `(owner_user_id, archived_at, updated_at)` and an owner-scoped uniqueness guard for active prompt names, using either a partial unique index on `(owner_user_id, lower(name)) WHERE archived_at IS NULL` or equivalent application-level validation if the SQLite version complicates expression indexes.

**Why**: Users expect saved prompts to follow their account, not just one browser. Owner scoping in the backend is the only reliable isolation boundary. Alternative - `localStorage` only - was rejected because it cannot support cross-device reuse or backend access control tests.

### 2. Add narrow prompt permissions and owner-filter every query

Add `prompts:read` and `prompts:write` permissions to authenticated product roles (`superadmin`, `admin`, `hr`, `pm`, `viewer` if viewers can chat). Endpoints use `require_permission(...)` or `get_current_identity` plus explicit permission checks. Every database operation includes `owner_user_id = identity.user_id`; client-supplied owner IDs are never accepted.

Suggested routes:
- `GET /saved-prompts?query=&limit=&include_archived=false`
- `POST /saved-prompts`
- `GET /saved-prompts/{prompt_id}`
- `PATCH /saved-prompts/{prompt_id}`
- `DELETE /saved-prompts/{prompt_id}` (soft-delete/archive)
- `POST /saved-prompts/{prompt_id}/use` (increments usage metadata and returns the prompt)

**Why**: A top-level `/saved-prompts` route keeps this feature independent of workspace selection. Alternative - workspace-scoped routes - was rejected for the initial version because prompts are user productivity assets, not workspace records.

### 3. Treat saved prompt variables as a template syntax, not arbitrary formatting

Use single-brace placeholders matching `{variable_name}` where `variable_name` matches `[A-Za-z][A-Za-z0-9_]{0,63}`. Extract variables in first-seen order and store them as metadata. Reject duplicate placeholders only when they differ by normalized casing; repeated exact placeholders are valid and receive one input field. Treat malformed placeholders as validation errors in create/edit UI and API responses. Support escaping literal braces with backslashes (`\{` and `\}`); do not treat `{{...}}` as a variable.

**Why**: The screenshots use `{country}` and OpenAI Playground prompt management documents `{variables}`. A narrow syntax avoids ambiguous JSON/object prompts and makes variable-fill dialogs deterministic. Alternative - Mustache-style `{{variable}}` - was rejected because this codebase already uses double braces for i18n interpolation.

### 4. Insert rendered prompt text into the composer at the current caret

Selecting a prompt never sends a chat turn. For prompts without variables, insert the body at the current textarea selection/caret, adding whitespace only when needed to avoid word collisions. For prompts with variables, open a variable-fill dialog, then render the body by replacing placeholders with provided values and insert the rendered text at the caret. After insertion, focus returns to the composer and the caret moves to the end of inserted text.

**Why**: Inserting rather than auto-sending keeps users in control and avoids accidental execution of stale or partially filled templates. Alternative - immediately start a new chat or send the prompt - was rejected because Cognitrix conversations often depend on workspace context and selected chart-generation options.

### 5. Model "Capabilities" as composer hints, not backend tool grants

The creation/edit modal includes optional capability hints matching current composer features and future extensibility. Initial values can map to existing UI affordances such as `file_upload`, `multi_chart`, and `data_labels`. Applying a saved prompt may preselect those composer options where applicable, but it does not bypass backend guardrails or grant any tool permission.

**Why**: The screenshot's "Capabilities (optional)" maps naturally to product tools, but Cognitrix tools are already governed by auth and agent guardrails. Alternative - persisting raw backend tool names - was rejected because it exposes implementation details and could create misleading privilege semantics.

### 6. Keep management inside the chat workflow first

Implement the primary management experience as a modal or overlay reachable from the composer menu. It includes search, a create button, list rows with previews, edit/delete actions, and an "insert" action for the active composer. A dedicated route can be added later, but this change should not add a new global sidebar destination.

**Why**: The screenshots show prompt management as a chat-adjacent workflow. Staying inside the composer reduces navigation cost and avoids expanding the app shell before there is a broader prompt-library IA.

### 7. Add hover-only actions to historical user messages

Add a compact action row to user-authored chat bubbles. The row appears on hover or keyboard focus and includes:
- save as prompt template, which opens the existing create prompt dialog with the historical message body prefilled and a derived editable name;
- copy prompt, which copies the exact historical message text to the clipboard and reports success or failure with the existing toast system.

Only user messages receive these prompt actions. Assistant answers, agent traces, chart cards, and ingestion confirmation controls do not receive them because saving generated responses as user prompt templates would blur the product meaning of "prompt".

**Why**: The saved-prompts menu helps future composition, but many valuable prompts are discovered after a successful analysis turn. Surfacing actions directly on the historical user bubble keeps the reuse workflow local and avoids forcing the user to manually select/copy text. Opening the existing create dialog instead of writing immediately preserves name editing, variable validation, duplicate-name handling, and optional capability selection.

### 8. Audit prompt lifecycle metadata only

Emit audit events for `saved_prompt_create`, `saved_prompt_update`, `saved_prompt_delete`, and `saved_prompt_use`. Event details may include prompt ID, owner ID, variable count, capability IDs, and success/failure status. They MUST NOT include the prompt name or body, because either can contain sensitive business context.

**Why**: Auditability matters, but prompt content is user-authored and may contain confidential data. Alternative - logging names for readability - was rejected because names can still leak customer, employee, or strategy details.

## Risks / Trade-offs

- **Prompt injection stored as a reusable asset**: A user can save malicious or careless instructions and reuse them repeatedly. Mitigation: saved prompts are ordinary user text, still pass through existing chat guardrails, and never become system/developer prompts.
- **Sensitive prompt content leakage**: Prompt bodies may include business or HR details. Mitigation: owner-filter every backend query, never log bodies/names to audit, and add user-isolation tests.
- **Variable parser false positives in JSON or code snippets**: BI prompts may include braces for examples. Mitigation: require strict variable names, support escaped braces, ignore double braces, and surface validation errors before save.
- **Composer menu complexity**: The existing chat input already has file upload, generation options, chart triggers, and column mentions. Mitigation: implement saved prompts as isolated child components/hooks, keep `ChatInput` orchestration thin, and add focused UI tests.
- **Message action discoverability**: Hover-only controls are intentionally quiet but can be missed. Mitigation: expose accessible labels/tooltips and show the row on keyboard focus as well as pointer hover.
- **Stale frontend cache after edits/deletes**: A prompt list may show old data across tabs. Mitigation: use TanStack Query invalidation after mutations and refetch on menu open/manage open.
- **Global user prompts vs workspace-specific context**: A prompt created in one workspace may be less relevant in another. Mitigation: initial version is user-global for speed and simplicity; add workspace tags/sharing only after usage data proves the need.

## Migration Plan

1. Add backend settings/migrations/store/router with the feature enabled by default for authenticated users; no existing data migration is required.
2. Add frontend API client/hooks and management UI behind the existing authenticated app surface.
3. Extend the chat composer "+" menu with saved prompts, preserving current file/generation option behavior.
4. Add API, security, and frontend tests before enabling in normal development builds.
5. Rollback by removing or hiding the frontend menu entry and unmounting the router; the SQLite table can remain inert without affecting existing chat or workspace state.

## Open Questions

- Should the first implementation include prompt export/import, or wait until team sharing/folders are specified? Recommendation: defer.
- Should capability hints include only current composer options or also future agent-tool categories? Recommendation: store a string array with a controlled allowlist so new values can be added later without schema changes.
