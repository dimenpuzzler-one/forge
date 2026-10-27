# ADR-010: A local directory is a source, not a trust grant

## Status

Accepted, 2026-10-27. Implemented in `forge_sources.local`; exposed as `forge import`.

## Context

The skills.sh API requires a Vercel OIDC token. Someone who installs Forge without one gets an
empty registry, and every command after `doctor` reports that nothing matched. The engine
worked; nobody outside the original setup could see it work.

Most people who care about Skills already have them on disk: a clone of a Skill repository,
`~/.claude/skills`, or a vendored folder in a project. Those files are no more trustworthy
because they are local. A cloned repository is exactly as untrusted as its upstream.

## Decision

`forge import <dir> --label <name>` registers every directory containing a `SKILL.md` as a
Skill with the id `local/<label>/<relative path>`, under a source named `local:<label>`.

1. **Same storage path.** Detail is stored through `Registry.store_detail`, the path used by
   `forge inspect`. Path validation, size limits, content hashing, immutable snapshots, and the
   static audit apply unchanged. A local Skill can be planned, pinned, composed, and diffed like
   any other.
2. **Same untrusted-data rule.** Files are read as UTF-8 text and never executed. Symlinks are
   not followed, so an import cannot read outside the directory it was given. Secret-looking
   files, binaries, VCS, and dependency folders are skipped and reported, never silently.
3. **Validate before registering.** A Skill over the size limit is rejected whole before any
   metadata is written. A metadata row without a cached version would make `inspect` try to
   fetch it from a remote source that has never heard of it.
4. **Re-import is versioning.** Importing the same label again adds a new immutable version
   only when content changed. Pins and earlier versions stay where they are.
5. **No remote fallback.** `inspect --refresh` and `audit-skill` on a local Skill never call
   skills.sh; they explain how to refresh locally and show the static audit.

## Consequences

- Forge is usable offline from the first command, and the test suite can exercise the whole
  workflow without a fixture registry.
- Local ids cannot collide with skills.sh ids, which never start with `local/`.
- Binary assets are not cached, so a bundle of a font- or image-heavy Skill is reference
  material, not a runnable copy. This is stated in the README rather than worked around.
- The static audit is lexical. A review checklist that names `curl` as something to look for
  is itself flagged. That is acceptable: the audit flags, a human decides.
