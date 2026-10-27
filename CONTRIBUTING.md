# Contributing to Forge

Thanks for helping. Forge is small on purpose, so a focused pull request with tests is the
fastest way to get a change in.

## Set up

```bash
git clone https://github.com/dimenpuzzler-one/forge && cd forge
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\Activate.ps1
python -m pip install --no-deps -e .
python -m unittest discover -s tests -t .
forge benchmark --output "$(mktemp -d)"
```

Python 3.12+ and the standard library only. Please do not add runtime dependencies; if a
change seems to need one, open an issue first.

## Ground rules

These come from [AGENTS.md](AGENTS.md) and the [ADRs](docs/decisions/). A pull request that
breaks one will be asked to change.

- External Skill files are untrusted data. Nothing in sync, import, search, or inspect may
  execute them.
- Skill versions and snapshots are immutable. Lockfiles change only through `forge pin`.
- Never read `.env*`, credentials, or private keys when scanning a project or importing Skills.
- Every schema change is a new SQLite migration step in `forge_registry.database`.
- A language model may propose; only the deterministic policy gate admits (ADR-006). Changes
  to the planner must keep `forge benchmark` at 6/6 policy probes.
- Tests run offline. Network code goes behind a transport seam the tests replace.

## Good first contributions

Open items from [IMPLEMENTATION_STATUS.md](docs/roadmap/IMPLEMENTATION_STATUS.md):

- an aggregate license warning for plans that mix incompatible Skill licenses;
- collapsing duplicate role assignments in a plan;
- more source adapters (for example, a GitHub repository by URL) built on the same
  validation path as `forge import`.

## Pull requests

- Describe the behaviour change and how you verified it.
- Add or update tests next to the code you touched (`tests/unit`, `tests/integration`).
- Update the README when a command or its output changes.

By contributing you agree that your contribution is licensed under the
[Apache License 2.0](LICENSE).
