# Vendored Skill Bundles

This directory contains skill zip bundles that the API installs on startup
when `AGENT_SKILLS_ENABLED=true`. Each entry below pins the upstream version
and sha256 of the vendored zip; the startup bootstrap verifies the local file
against the recorded checksum before installing it.

If the recorded checksum does not match the file on disk, the bootstrap
**refuses to install** the skill (it does not crash the API) and the failure
surfaces in `GET /admin/skills` once the API is up. A super-admin can then
upload a correct version through the admin UI.

## anthropic/xlsx

- **File:** `anthropic-xlsx-<version>.zip`
- **Upstream:** https://mcpservers.org/agent-skills/anthropic/xlsx
- **Version:** _to be filled in after the bundle is vendored_
- **Upstream sha256:** _to be filled in after the bundle is vendored_

To vendor or update the bundle:

1. Download the zip from the upstream URL above.
2. Compute its sha256: `shasum -a 256 anthropic-xlsx-<version>.zip`.
3. Save the file as `apps/api/vendor/skills/anthropic-xlsx-<version>.zip`.
4. Replace the `Version` and `Upstream sha256` lines above with the real values.
5. Restart the API. The startup bootstrap will install and assign the skill to
   `WriteIngestionAgent`.

If multiple `anthropic-xlsx-*.zip` files are present the bootstrap picks the
one whose filename version matches the `Version` line above.
