# MVP-0 architecture

Forge's source repository is the engine. The user data directory (`FORGE_HOME`, otherwise `~/.forge`) contains the SQLite registry, HTTP cache, immutable snapshots, sessions, and logs.

```text
skills.sh JSON --Source Adapter--> SQLite Registry --FTS5--> CLI search
                                         |
                                         +-- immutable detail snapshot (on inspect)

project files --safe scanner--> <project>/.forge/project.json
```

The adapter consumes JSON only. Untrusted Skill files are validated for path and size before caching; they are never executed by `sync`, `search`, or `inspect`.

