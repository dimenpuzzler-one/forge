# ADR-003: Immutable Skill versions and project locks

Each `(skill_id, content_hash)` is immutable. New upstream content creates a new version; later project lock support must retain the selected hash until a user explicitly changes it.

