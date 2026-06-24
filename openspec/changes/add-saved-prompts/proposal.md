## Why

Cognitrix users currently retype or externally store high-value BI prompts, which makes repeated analysis workflows slow, inconsistent, and invisible to the product. ChatGPT-style saved prompts are now a familiar interaction pattern: users expect to create a named prompt once, optionally parameterize it with `{variables}`, find it from the chat composer, and reuse it without breaking their current conversation flow.

## What Changes

- Add a first-class **Saved Prompt** model: a user-owned reusable prompt with name, body, extracted variable placeholders, optional enabled tool/capability hints, timestamps, and soft-delete/archive state.
- Add authenticated REST APIs to create, list/search, update, delete/archive, and retrieve saved prompts for the current user. Prompts are private to the owner in this change; team/workspace sharing is explicitly deferred.
- Add a ChatGPT-like saved prompts entry under the chat composer "+" menu:
  - top-level "Saved prompts" row with a submenu;
  - "Create prompt" opens a modal matching the screenshot flow;
  - "Manage prompts" opens a full management view/dialog;
  - recent or matching saved prompts can be inserted directly into the composer.
- Add a prompt creation/editing modal with name and prompt body fields, `{variable}` detection, duplicate/invalid variable validation, optional capability/tool selection, disabled save state, and localized help text.
- Add a management surface with search, empty state, create button, prompt list rows with previews, edit/delete actions, and insertion into the active composer.
- Add variable-fill behavior on insertion: prompts without variables insert directly; prompts with variables ask for values and render the final prompt text into the composer at the current cursor position.
- Add frontend state and API client support so saved prompts sync across browsers/devices through the backend, with local query caching only as a performance layer.
- Add audit events for create/update/delete/use actions, recording metadata only; prompt bodies are never written to audit logs.
- No breaking API or data-model changes for chat, ingestion, workspaces, or existing saved views.

## Capabilities

### New Capabilities
- `saved-prompts`: User-owned prompt library for creating, managing, searching, parameterizing, and inserting reusable prompts from the chat composer.

### Modified Capabilities
<!-- None. Existing chat behavior remains unchanged unless a user explicitly inserts a saved prompt. -->

## Impact

- **Backend (`apps/api/`)**:
  - New module/router for saved prompts, likely `saved_prompts.py`, mounted from `main.py`.
  - New SQLite state table(s) under `UPLOAD_DIR/state/`, preferably in a dedicated `saved_prompts.sqlite3` or existing state DB following the repo's one-concern-per-store pattern.
  - `auth.py` permission surface may add a narrow `prompts:read` / `prompts:write` pair, granted to authenticated product roles.
  - `audit.py` emits metadata-only prompt lifecycle/use events.
- **Frontend (`apps/web/`)**:
  - Extend `components/chat/chat-input.tsx` "+" menu with the saved-prompts submenu and insertion wiring.
  - New `components/chat/saved-prompts-*` components for create/edit modal, variable-fill dialog, and management view.
  - New `lib/saved-prompts/` API client and hooks, plus i18n keys in `lib/i18n/dictionary.ts`.
  - Optional route or modal-driven page for "Manage prompts"; the initial product path should work from the composer without requiring global navigation changes.
- **Data / Privacy**:
  - Saved prompt bodies are scoped to the authenticated `user_id`; no workspace/team sharing in this change.
  - Prompt bodies may contain sensitive business context, so search APIs must not leak across users and audit logs must avoid prompt content.
- **Tests**:
  - API tests for CRUD, user isolation, validation, and audit redaction.
  - Frontend unit tests for menu behavior, modal validation, search/list management, and variable insertion.
  - Store/API tests for cache invalidation and cross-session composer insertion.
