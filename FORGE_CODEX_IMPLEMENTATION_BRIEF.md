# FORGE — Codex 구현 작업지시서

> 대상 저장소: `https://github.com/dimenpuzzler-one/forge`
>
> 로컬 작업 루트: `C:\dev\forge`
>
> 문서 목적: Codex가 이 문서 하나를 읽고 Forge의 장기 비전, 핵심 불변조건, 모노레포 아키텍처, 데이터 구조, 동기화 방식, 프로젝트 적용 방식, Skill 탐색/조합/실험 기능, 단계별 구현 순서를 놓치지 않고 작업할 수 있게 한다.
>
> 기준일: 2026-08-11
>
> 중요: 이 문서는 “한 번에 모든 기능을 완성하라”는 뜻이 아니다. **장기 구조는 보존하되, 작동하는 수직 슬라이스를 단계적으로 완성**한다.

---

# 0. Codex에게 가장 먼저 전달할 지시

이 프로젝트는 단순한 `skills.sh 크롤러`가 아니다.

Forge의 장기 정체성은 다음과 같다.

> **Forge = Open Skill Exploration & Engineering Toolkit**
>
> 공개된 Agent Skill들을 수집·동기화·검색·평가·비교·조합·실험하고,
> 필요하면 현재 소프트웨어 프로젝트의 문맥을 읽어 적합한 Skill을 추천·고정·적용하며,
> 장기적으로 사용자의 실제 프로젝트 경험까지 다시 재사용 가능한 Skill/Pattern으로 축적하는
> **Local-first Skill R&D Platform**이다.

한국어로 풀면 다음 네 가지가 동시에 존재한다.

1. **Skill Registry** — 스킬 저장·버전·출처 관리소
2. **Skill Explorer / Search Engine** — 언제든 스킬을 찾아보고 읽고 비교하는 검색도구
3. **Skill Playground / Composer** — 여러 스킬을 조합하며 새로운 워크플로와 제품 아이디어를 실험하는 놀이터
4. **Project Engineering Layer** — 현재 레포를 읽고 필요한 스킬을 추천·고정·주입·검증하는 개발 도구

초기에는 CLI 중심으로 만든다.
웹 UI, Skill Graph, Opportunity Finder, Agent Benchmark 등은 이후 같은 모노레포 안에서 확장한다.

---

# 1. 프로젝트를 이렇게 이해할 것

## 1.1 해결하려는 문제

현재 Agent Skill 생태계에는 수천~수만 개 규모의 공개 Skill이 존재할 수 있다.
정확한 총 개수는 수집 기준에 따라 달라지므로 **코드나 문서에 18,000 같은 특정 숫자를 상수로 박지 않는다.**

문제는 “Skill이 부족하다”가 아니다.

문제는 다음이다.

- 어떤 Skill이 존재하는지 기억하기 어렵다.
- 검색할 때마다 외부 사이트에 다시 가야 한다.
- 비슷한 Skill이 많고 품질 차이가 크다.
- upstream이 바뀌어도 과거에 어떤 버전을 썼는지 알기 어렵다.
- 공개 Skill이 안전한지 알기 어렵다.
- 특정 프로젝트에 어떤 Skill이 적합한지 사람이 매번 판단해야 한다.
- 좋은 Skill 여러 개를 조합했을 때 새로운 workflow/product가 될 수 있는데 이를 체계적으로 탐색하기 어렵다.
- 실제 프로젝트에서 얻은 귀중한 시행착오가 다음 프로젝트로 자동 누적되지 않는다.

Forge는 이 문제들을 하나의 장기 플랫폼 안에서 푼다.

---

# 2. 핵심 철학과 불변조건

이 항목은 구현 편의를 이유로 함부로 바꾸지 않는다.
변경이 필요하면 ADR(Architecture Decision Record)을 먼저 남긴다.

## 2.1 Forge repository와 Skill data를 분리한다

**Forge Git repository는 엔진이다. 외부 Skill 원문은 데이터다.**

외부 Skill 수천~수만 개를 Forge Git repository에 커밋하지 않는다.

```text
C:\dev\forge
    = 코드, 테스트, 문서, schema, local skill 예제

사용자 데이터 디렉터리
    = registry DB, upstream snapshot, cache, audit, embeddings
```

기본 사용자 데이터 위치는 OS 독립적으로 계산한다.

권장 우선순위:

1. 환경변수 `FORGE_HOME`
2. 없으면 사용자 홈의 `.forge`

Windows 예:

```text
C:\Users\<user>\.forge\
```

프로젝트별 `.forge/`와 전역 `~/.forge/`를 혼동하지 않는다.

---

## 2.2 Local-first

초기 Forge는 서버가 없어도 핵심 기능이 돌아가야 한다.

필수 핵심 기능:

- sync
- search
- inspect
- project scan
- recommend
- pin/lock
- compose

는 로컬 SQLite와 파일 캐시만으로 동작한다.

웹 SaaS와 클라우드 DB는 미래 옵션이지 초기 필수조건이 아니다.

---

## 2.3 외부 Skill은 신뢰하지 않는다

외부 `SKILL.md`, scripts, references는 **untrusted input**이다.

동기화나 검색 과정에서 절대 자동 실행하지 않는다.

특히 다음을 금지한다.

- sync 중 외부 script 실행
- inspect만 했는데 script 실행
- upstream update 발견 즉시 프로젝트에 자동 적용
- 외부 Skill의 지시를 Forge 자신의 시스템 명령처럼 실행
- archive/path traversal 허용
- `.env`, credential, token을 Skill context에 자동 포함

외부 Skill은 먼저 **문서/데이터**로 취급한다.

실행은 명시적인 사용자 선택 + runtime policy를 통과한 뒤 별도 단계에서만 가능하게 설계한다.

---

## 2.4 Update detection과 Update adoption을 분리한다

upstream 변화 발견은 자동화해도 된다.

그러나 프로젝트가 쓰는 Skill 버전을 자동으로 최신으로 덮어쓰지 않는다.

```text
upstream change detected
        ↓
new immutable version stored
        ↓
diff / audit / metadata updated
        ↓
"update available"
        ↓
explicit pin/promote
```

프로젝트의 `skills.lock`은 재현성을 위해 기존 hash/version을 유지한다.

---

## 2.5 Deterministic first, LLM optional

Forge 자체가 AI 관련 프로젝트라고 해서 모든 것을 LLM으로 해결하지 않는다.

우선순위:

```text
deterministic parser / metadata / hash / FTS
        ↓
rule-based ranking
        ↓
optional embeddings
        ↓
optional LLM reasoning
```

Forge core는 OpenAI/Anthropic API key가 없어도 사용할 수 있어야 한다.

LLM은 다음과 같은 고차원 기능에만 선택적으로 사용한다.

- Skill semantic enrichment
- 복합 Project recommendation 설명
- Skill composition 아이디어
- Local Skill extraction
- Opportunity Finder
- architecture/repo audit reasoning

---

## 2.6 Provenance를 잃지 않는다

모든 Skill은 최소한 다음을 추적할 수 있어야 한다.

- source
- source type
- repository/provider
- skill id
- slug/name
- upstream URL
- first seen
- last seen
- content hash
- version observed time
- Git commit SHA (확보 가능할 때)
- license metadata
- security audit state
- exact files belonging to that version

“어디서 왔는지 모르는 복사본”을 만들지 않는다.

---

# 3. 현재 확인된 외부 인터페이스

구현 시작 시 Codex는 공식 문서를 다시 확인하고 contract test 또는 adapter test를 작성한다.
외부 API는 변경될 수 있으므로 core domain에 endpoint shape를 직접 퍼뜨리지 않는다.

현재 skills.sh 공식 API에서 중요한 개념:

```text
GET /api/v1/skills
GET /api/v1/skills/search
GET /api/v1/skills/curated
GET /api/v1/skills/{id}
GET /api/v1/skills/audit/{id}
```

현재 detail 응답에는 Skill의 `hash`와 전체 file tree가 포함될 수 있다.

`hash`는 change detection/cache invalidation에 활용한다.

현재 listing은 pagination을 지원한다.

공식 `skills` CLI도 별도로 존재한다.

```text
npx skills add ...
npx skills find ...
npx skills check
npx skills update
```

Forge는 공식 CLI를 무조건 대체하려는 프로젝트가 아니다.

역할을 구분한다.

```text
official skills CLI
    = install/manage agent skills

Forge
    = discover/mirror/version/search/evaluate/compose/project-context/pin
```

필요하면 Agent Adapter에서 공식 CLI를 호출할 수 있지만 core registry와 강결합하지 않는다.

---

# 4. 기존 README Collector의 위치와 처리

사용자는 이미 `C:\dev` 아래 어딘가에 README Collector 프로그램을 만들어 두었다.
아직 GitHub repository로 관리하지 않았으며 정확한 디렉터리 이름은 이 문서에 고정되어 있지 않다.

## Codex의 첫 작업 중 하나

`C:\dev`를 안전하게 조사하여 기존 README Collector 프로젝트를 식별한다.

찾을 때 다음 신호를 이용한다.

- README 파일을 재귀적으로 찾는 코드
- 여러 프로젝트 README를 복사/수집하는 기능
- 현재 제공된 프로젝트 README들을 생성한 흔적
- Python/PowerShell/Node script
- README collector라는 이름 또는 유사 기능

### 절대 금지

기존 Collector를 바로 이동하거나 삭제하지 않는다.

먼저:

1. 위치 확인
2. 현재 기능 파악
3. 실행법 파악
4. 입력/출력 예시 확인
5. 기존 동작을 보존하는 regression test 작성
6. Forge의 `project scanner`로 코드 또는 아이디어를 port
7. 신규 scanner가 기존 핵심 동작을 재현하는지 확인

그 이후에도 원본 삭제는 사용자 별도 지시가 없으면 하지 않는다.

---

# 5. README Collector의 장기 역할

README Collector는 Forge 내부에서 단순 수집기가 아니라:

> **Project Context Collector / Project Scanner**

로 진화한다.

초기:

```text
README 읽기
```

장기:

```text
README
package.json
pyproject.toml
workspace config
lock files
AGENTS.md
CLAUDE.md
handoff docs
architecture docs
Git state
directory tree
test commands
deployment hints
known TODO / known debt
```

를 안전하게 읽어 Project Context를 생성한다.

단, `.env`, secret, credentials는 스캔 대상에서 기본 제외한다.

---

# 6. 추천 모노레포 구조

초기에 쓸데없이 20개의 빈 package를 만들지 말 것.
하지만 아래 경계는 유지한다.

```text
forge/
├── README.md
├── AGENTS.md
├── pyproject.toml
├── .gitignore
│
├── apps/
│   ├── cli/
│   │   └── Forge CLI entrypoint
│   │
│   ├── web/
│   │   └── future: Skill Explorer Web UI
│   │
│   └── playground/
│       └── future: composition playground UI
│
├── packages/
│   ├── core/
│   │   ├── shared domain models
│   │   ├── config
│   │   ├── paths
│   │   └── error types
│   │
│   ├── registry/
│   │   ├── SQLite schema
│   │   ├── repositories
│   │   └── version/provenance models
│   │
│   ├── sources/
│   │   ├── SourceAdapter interface
│   │   ├── skills_sh
│   │   └── github
│   │
│   ├── search/
│   │   ├── FTS
│   │   ├── filters
│   │   └── ranking
│   │
│   ├── project/
│   │   ├── scanner
│   │   ├── context schema
│   │   ├── lockfile
│   │   └── project policy
│   │
│   ├── compose/
│   │   ├── composition manifest
│   │   └── compatibility analysis
│   │
│   ├── evaluate/
│   │   ├── security
│   │   ├── quality
│   │   ├── duplication
│   │   └── license
│   │
│   ├── runtime/
│   │   ├── materialization
│   │   ├── execution policy
│   │   └── session bundle
│   │
│   └── adapters/
│       ├── generic-filesystem
│       ├── codex        # future
│       ├── claude       # future
│       └── others       # future
│
├── labs/
│   ├── opportunity-finder/
│   ├── repo-auditor/
│   ├── agent-benchmark/
│   └── skill-graph/
│
├── skills/
│   └── local/
│       └── Forge/사용자 자체 Skill만 Git 추적 가능
│
├── docs/
│   ├── architecture/
│   ├── decisions/
│   ├── roadmap/
│   └── research/
│
├── scripts/
└── tests/
    ├── unit/
    ├── integration/
    ├── fixtures/
    └── contract/
```

## 초기 구현 언어

초기 CLI/core는 **Python 3.12+**를 우선한다.

이유:

- filesystem 탐색
- SQLite
- Markdown parsing
- HTTP sync
- data processing
- 향후 embeddings/analysis

에 적합하다.

웹 UI가 필요해질 때 `apps/web`에 Next.js/TypeScript를 추가한다.
초기부터 Node와 Python을 동시에 구축하느라 시간을 낭비하지 않는다.

특정 monorepo orchestrator는 필요성이 생기기 전까지 도입하지 않는다.

---

# 7. 전역 데이터 디렉터리

예시:

```text
~/.forge/
├── forge.db
├── cache/
│   ├── skills/
│   ├── github/
│   └── http/
├── snapshots/
│   └── <source>/<skill-id>/<hash>/
├── sessions/
├── logs/
└── config.toml
```

Git repository에는 포함하지 않는다.

---

# 8. Project-local `.forge` 구조

Forge를 특정 프로젝트에서 사용할 때 해당 프로젝트 root에 작은 메타 디렉터리를 둘 수 있다.

```text
<project>/
├── .forge/
│   ├── project.json
│   ├── skills.lock
│   ├── policy.yaml
│   └── history.jsonl
```

## 8.1 `project.json`

Project Scanner가 생성한 현재 프로젝트의 기계 가독 context.

예:

```json
{
  "schemaVersion": 1,
  "name": "stockback",
  "root": "C:\\dev\\stockback",
  "languages": ["python"],
  "stack": [],
  "domains": ["quant", "backtesting", "kr-equity"],
  "architecture": [
    "strategy-plugin",
    "shared-validation-kernel",
    "immutable-experiment-results"
  ],
  "commands": {
    "test": ["python -m pytest -q"]
  },
  "currentStage": "data-validation",
  "detectedDocuments": [
    "README.md",
    "docs/decisions.md"
  ],
  "generatedAt": "...",
  "sourceFingerprint": "..."
}
```

이 파일은 재생성 가능해야 한다.

민감정보를 넣지 않는다.

---

## 8.2 `skills.lock`

실제로 프로젝트에서 선택/고정한 Skill 버전.

개념 예:

```yaml
schemaVersion: 1
skills:
  - id: supabase/agent-skills/supabase-postgres-best-practices
    source: supabase/agent-skills
    hash: abc123
    gitCommit: optional-sha
    pinnedAt: 2026-08-11T00:00:00Z
    reason: Supabase RLS and production DB review
    mode: reference
```

lockfile의 핵심 목적은:

- 재현성
- update drift 방지
- provenance
- 어떤 Skill을 왜 사용했는지 추적

이다.

---

## 8.3 `policy.yaml`

예:

```yaml
allowScriptExecution: false
requireSecurityAudit: true
minimumTrust: warn
allowUnknownLicense: true
autoUpdatePinnedSkills: false
```

초기에는 정책 스키마만 작게 만든다.

---

# 9. Registry 데이터 모델

초기 DB는 SQLite를 사용한다.

SQLite migration을 버전 관리한다.

최소 테이블 제안:

## `sources`

```text
id
name
type
base_url
enabled
last_sync_at
sync_cursor
```

## `skills`

```text
id                  stable Forge identifier
upstream_id
source_id
slug
name
description
source_repo
source_type
install_url
skills_sh_url
install_count
is_duplicate
first_seen_at
last_seen_at
latest_seen_version_id
trusted_version_id nullable
```

## `skill_versions`

불변 snapshot 개념.

```text
id
skill_id
content_hash
git_commit_sha nullable
observed_at
file_count
total_bytes
license_spdx nullable
license_status
security_status
risk_level
```

동일 `skill_id + content_hash`는 중복 생성하지 않는다.

## `skill_files`

```text
id
skill_version_id
path
content_hash
size
media_type
contents nullable
is_entrypoint
is_script
```

metadata-only sync에서는 `contents`가 없어도 된다.

## `security_audits`

```text
skill_version_id
provider
status
risk_level
summary
audited_at
raw_json
```

## `tags`

## `skill_tags`

## `collections`

사용자의 즐겨찾기/묶음.

## `compositions`

Skill 조합 실험.

## `composition_skills`

## `project_profiles`

선택적으로 전역 DB에도 project summary를 저장할 수 있다.

## `project_skill_usage`

프로젝트와 Skill 사용 이력.

## 미래 테이블

- embeddings
- skill_edges
- local_evaluations
- benchmark_runs
- opportunities

초기 migration에 미래 테이블을 전부 만들 필요는 없다.

---

# 10. Source Adapter

외부 source마다 core가 달라지지 않도록 interface를 둔다.

개념:

```python
class SkillSourceAdapter(Protocol):
    def list_skills(...): ...
    def fetch_skill(...): ...
    def fetch_audit(...): ...
    def resolve_provenance(...): ...
```

초기 adapter:

1. `skills_sh`
2. `github`

향후:

- well-known skill sources
- local folders
- custom Git repositories
- curated private registry

---

# 11. skills.sh Sync 설계

## 11.1 첫 sync는 metadata-first

처음부터 모든 Skill의 전체 supporting files를 다운로드하지 않는다.

```text
Phase A
list metadata for all available skills
        ↓
store/update skills rows
        ↓
search becomes usable quickly
```

그 다음:

```text
Phase B
curated / selected / popular / requested skill detail fetch
```

그리고:

```text
Phase C
on-demand detail fetch
```

---

## 11.2 Pagination / resume

대규모 sync는 중단될 수 있다.

반드시:

- cursor/page state 기록
- retry
- exponential backoff
- 429 `Retry-After` 존중
- timeout
- partial progress commit
- resume

를 지원한다.

중간 실패를 전체 실패로 만들지 않는다.

---

## 11.3 Hash 기반 변화 탐지

detail에 content hash가 존재하면 활용한다.

```text
known hash == upstream hash
    → unchanged
    → skip full reprocessing

known hash != upstream hash
    → create new immutable version
    → fetch files
    → diff/evaluate
```

upstream version을 기존 snapshot 위에 덮어쓰지 않는다.

---

## 11.4 GitHub provenance

GitHub source는 가능하면 다음을 추가로 기록한다.

- repository full name
- default branch
- commit/tree SHA
- license
- source path
- repository archived 여부

그러나 skills.sh metadata sync를 GitHub API 호출 수천 건으로 폭발시키지 않는다.

GitHub enrichment는:

- on-demand
- selected skill
- trusted/curated
- changed skill

중심으로 수행한다.

---

# 12. Search Engine

## 12.1 1차는 SQLite FTS5

처음부터 vector DB를 붙이지 않는다.

검색 필드:

- name
- description
- source
- owner
- tags
- fetched `SKILL.md` text

예:

```powershell
forge search "postgres production"
forge search "playwright mobile payment"
forge search "backtesting robustness"
```

결과에는 최소한:

```text
rank
skill id
name
source
short description
install count
official/curated flag
security status
risk level
cached/detail fetched state
```

를 보여준다.

---

## 12.2 Filter

장기적으로:

```text
--official
--owner
--risk
--license
--has-script
--cached
--tag
--updated-after
```

등을 지원한다.

---

## 12.3 Hybrid/Semantic은 2차

embeddings를 붙일 때도 기존 FTS를 버리지 않는다.

```text
lexical relevance
+ semantic relevance
+ project stack match
+ trust/audit
+ freshness
+ user history
```

를 별도 feature로 계산한다.

하나의 “절대 품질 점수”로 위장하지 않는다.
각 dimension을 설명 가능하게 유지한다.

---

# 13. `forge inspect`

사용자가 아무 때고 Skill을 가지고 놀 수 있게 하는 핵심 기능이다.

```powershell
forge inspect <skill-id>
```

표시:

- metadata
- source
- installs
- provenance
- current/local hash
- upstream status
- security audit
- license
- file tree
- `SKILL.md`
- supporting files 목록
- script 존재 여부
- similar skills
- collections/favorites

detail이 local cache에 없으면 fetch할 수 있다.

외부 script는 inspect로 실행하지 않는다.

---

# 14. Favorites / Collections

Skill을 단순 검색하고 끝내지 않고 개인 지식 자산으로 묶는다.

예:

```powershell
forge collection create "production-saas"
forge collection add "production-saas" <skill-id>
forge collection show "production-saas"
```

예상 collection:

- production-saas
- supabase
- react-nextjs
- agent-runtime
- quant-research
- payments
- observability
- security
- product-growth

---

# 15. Skill Playground / Composer

Forge의 중요한 정체성이다.

사용자는 Skill을 “업무 때문에만” 찾는 것이 아니라,
아무 때나 검색하고 여러 개를 섞어보며 무엇이 가능한지 탐색하고 싶다.

## 15.1 Composition은 원본 merge가 아니다

원본 Skill 파일을 뒤섞어 provenance를 잃지 않는다.

대신 별도의 Composition Manifest를 만든다.

예:

```yaml
name: production-supabase-saas
goal: Production-grade Supabase SaaS review
skills:
  - id: skill-A
    hash: ...
    role: database
  - id: skill-B
    hash: ...
    role: security
  - id: skill-C
    hash: ...
    role: testing
order:
  - architecture-review
  - security-review
  - test-gap-review
constraints:
  executeScripts: false
```

---

## 15.2 CLI

장기 예:

```powershell
forge compose add <skill-a> <skill-b> <skill-c> --name my-stack
forge compose show my-stack
forge compose analyze my-stack --goal "AI SaaS production readiness"
forge play my-stack
```

`analyze`에 LLM이 필요할 경우 optional provider로 둔다.

---

# 16. Skill Graph

후속 Labs 기능.

Skill 관계 예:

```text
similar_to
works_with
alternative_to
extends
requires
conflicts_with
same_source
same_stack
co_used
```

초기에는 metadata/tag/co-occurrence 기반 edge만 생성한다.

LLM이 생성한 관계는 deterministic relation과 구분해서 저장한다.

---

# 17. Project Scanner

## 17.1 실행

```powershell
cd C:\dev\stockback
forge scan
```

또는:

```powershell
forge scan C:\dev\stockback
```

---

## 17.2 Root detection

우선:

1. explicit path
2. current working directory
3. Git root detection

---

## 17.3 읽어도 되는 파일

기본 allowlist/heuristic:

- README*
- AGENTS.md
- CLAUDE.md
- package.json
- pyproject.toml
- requirements*.txt
- pnpm-workspace.yaml
- turbo.json
- tsconfig
- lock file metadata
- docs architecture/handoff/decision index
- test config
- deployment config names
- directory tree

---

## 17.4 기본 제외

- `.env*`
- secret files
- private keys
- credentials
- `.git`
- node_modules
- virtualenv
- build output
- large data
- raw user datasets
- binary blobs

---

## 17.5 생성할 Context

다음 dimension을 구조화한다.

- project name
- repo/root
- languages
- framework/stack
- domain
- architecture patterns
- data stores
- auth
- AI/LLM usage
- payments
- deployment
- test tooling
- commands
- important docs
- current stage
- known gaps/debt
- dangerous operations
- project-specific invariants

단, “알 수 없는 것”을 억지로 채우지 않는다.

---

# 18. `forge recommend`

Project Context와 Skill Registry를 연결하는 기능.

```powershell
cd C:\dev\grit-business-diagnostic
forge recommend
```

추천 결과 예:

```text
1. Playwright E2E
   이유: 현재 web/admin 서비스가 있고 일부 경로가 미검증

2. Supabase/Postgres production safety
   이유: migration/RLS/remote seed가 존재

3. Analytics/conversion tracking
   이유: 현재 프로젝트 gap으로 감지

4. PDF generation
   이유: browser print는 있으나 server PDF가 미구현
```

각 recommendation은 반드시:

- 왜 추천됐는지
- 어떤 project evidence 때문인지
- 어떤 위험/제약이 있는지
- 이미 사용 중인 유사 Skill이 있는지

를 보여준다.

단순 “Top 10 popular skills”가 되면 실패다.

---

# 19. 기존 프로젝트에 Skill 적용

## 19.1 `forge pin`

```powershell
forge pin <skill-id>
```

현재 프로젝트의 `skills.lock`에 exact version/hash를 기록한다.

---

## 19.2 `forge use`

장기적으로:

```powershell
forge use <skill-id>
```

동작 개념:

```text
resolve pinned/candidate version
        ↓
policy validation
        ↓
materialize temporary session bundle
        ↓
Agent Adapter
        ↓
AI coding agent reads selected skill context
```

외부 Skill 원본을 프로젝트 source tree 곳곳에 무작정 복사하지 않는다.

---

## 19.3 Session materialization

프로젝트 내부:

```text
.forge/session/<session-id>/
├── manifest.json
├── project-context.json
└── skills/
```

또는 global temp dir을 사용할 수 있다.

session 종료 후 정리 가능해야 한다.

---

# 20. Agent Adapter

Forge는 특정 Agent에 종속되지 않는다.

개념:

```python
class AgentAdapter(Protocol):
    def prepare_session(project_context, skill_versions, goal): ...
    def render_instructions(...): ...
    def cleanup(...): ...
```

초기에는 `generic-filesystem` adapter만 실제 구현해도 된다.

그 adapter는:

- selected Skill files
- project context
- composition manifest
- provenance

를 하나의 directory bundle로 만든다.

향후:

- Codex
- Claude Code
- Cursor
- Gemini CLI
- 기타 Agent

별 adapter를 추가한다.

각 agent의 Skill 설치 규칙이 다르더라도 Forge core는 바뀌지 않아야 한다.

---

# 21. `forge audit`

장기 Project feature.

현재 repo를 읽고:

```text
architecture
security
database
testing
observability
deployment
documentation drift
```

등의 gap을 찾는다.

그리고 gap마다 Registry Skill을 연결한다.

```text
gap detected
    ↓
search relevant skills
    ↓
recommend
    ↓
optionally apply
    ↓
verify
```

초기 버전에서 자동 수정까지 만들 필요는 없다.

---

# 22. Skill Evaluator

“많은 Skill”보다 “믿고 쓸 수 있는 Skill”이 중요하다.

평가 dimension:

- source trust
- official/curated
- install/popularity signal
- upstream activity
- security audit
- script presence
- license clarity
- duplicate status
- documentation completeness
- references/scripts structure
- known compatibility
- local usage history
- user feedback

`quality = 87` 같은 단일 숫자를 맹신하지 않는다.

가능하면 dimension별로 보여준다.

---

# 23. Security Pipeline

외부 Skill 신규/변경 발견 시:

```text
fetch
    ↓
path/size validation
    ↓
hash
    ↓
official security audit import
    ↓
static local checks
    ↓
script flagging
    ↓
candidate version
```

초기 local static checks:

- path traversal
- unexpectedly large file
- binary executable
- suspicious shell/download commands flag
- secrets-like patterns
- encoded payloads
- instruction to exfiltrate credentials
- hidden files

이 결과는 “절대 안전” 보증이 아니다.
risk signal이다.

---

# 24. License / Redistribution

공개 GitHub repository라고 해서 저작권이 없는 것이 아니다.

반드시:

- repository license
- skill-level license 가능 여부
- SPDX 가능하면 저장
- unknown license 구분
- attribution/provenance

를 보존한다.

특히 미래 `apps/web`을 공개할 때:

**license가 불명확한 Skill의 전체 원문을 공개 웹에서 재배포하는 것을 기본 동작으로 만들지 않는다.**

공개 web은 기본적으로:

- metadata
- description
- provenance
- link
- locally-computed evaluation

중심으로 설계하고,
full content 공개는 license policy를 통과해야 한다.

로컬 개인 Explorer에서는 cache된 원문 열람이 가능하다.

---

# 25. 기존 프로젝트별 예상 활용 사례

Project Scanner와 Recommender 설계 시 아래 실제 유형을 염두에 둔다.

## 25.1 64Patterns / iching

특징:

- Next.js
- Supabase
- OpenAI multi-call
- KSNET 결제
- deterministic I Ching calculation
- LLM은 해석/문장화 역할
- server-side payment amount/order validation
- production payment path 검증이 중요

추천 Skill category:

- Next.js
- Supabase/RLS
- payment security
- idempotency
- E2E
- observability
- structured output
- LLM reliability

Forge가 프로젝트에서 역추출할 수 있는 local pattern 후보:

- `safe-payment-state-machine`
- `deterministic-llm-boundary`
- `production-readme-sync`

---

## 25.2 ORACROSS

특징:

- Turborepo
- Next.js
- Supabase
- deterministic 3-system calculation
- facts → rules → LLM narrative
- Structured Outputs
- staged long-form generation
- entitlement/RPC/RLS
- payment/coupon
- PDF/browser regression
- mobile UI validation

추천 category:

- React/Next.js quality
- mobile/E2E
- Supabase
- structured outputs
- LLM evaluation
- observability
- long-running generation
- payment
- PDF regression

Local Skill 후보:

- `structured-output-gateway`
- `staged-ai-generation`
- `atomic-entitlement`
- `evidence-first-ai-report`
- `payment-idempotency`

---

## 25.3 GRIT 기업진단

특징:

- web + admin monorepo
- deterministic diagnosis engine
- LLM report engine
- Supabase
- RLS/RPC
- seed-driven rules
- analytics 미구현/확장
- server PDF 향후
- production seed 동기화 위험
- E2E / CRM / policy engine

추천 category:

- safe database deployment
- Supabase RLS
- Playwright
- analytics/conversion
- PDF
- CRM architecture
- observability
- payments

Local Skill 후보:

- `safe-supabase-seed-sync`
- `deterministic-diagnosis-engine`
- `report-section-parallelization`

---

## 25.4 stockback

특징:

- Python
- 한국주식
- data point-in-time correctness
- strategy plugin
- shared backtest/execution/risk kernel
- experiment immutability
- CREON 32-bit collection isolation
- robustness/work-forward
- research auditability

추천 category:

- Python testing
- data quality
- reproducible research
- point-in-time data
- backtesting
- experiment design
- market microstructure
- logging/ledger

Local Skill 후보:

- `quant-experiment-registration`
- `point-in-time-validation`
- `execution-assumption-audit`
- `reproducible-backtest`

---

## 25.5 coinback

특징:

- crypto futures research
- large validation history
- test suite
- walk-forward
- Monte Carlo
- execution F0/F1/F2
- AggTrade
- liquidation data
- data hash/sealed split
- live transport/L2 calibration은 별도 과제

추천 category:

- exchange execution
- market microstructure
- latency
- BBO/L2
- Python testing
- reproducibility
- live/paper promotion

Local Skill 후보:

- `backtest-to-paper-promotion`
- `execution-model-validation`
- `experiment-ledger`
- `microstructure-calibration`

---

# 26. Forge 자체가 Local Skill을 만들어야 하는 이유

외부 Skills는 초기 자본이다.

장기적으로 가장 가치 있는 것은:

```text
외부 Skill
+
실제 프로젝트에서 검증된 패턴
+
실패 경험
+
프로젝트별 운영 규칙
```

이다.

따라서 후속 기능:

```powershell
forge learn
```

또는:

```powershell
forge extract-skill
```

을 고려한다.

입력:

- project README
- ADR
- git diff
- tests
- experiment log
- runbook

출력 후보:

```text
Reusable Pattern Proposal
```

처음부터 자동으로 `SKILL.md`를 확정하지 않는다.

```text
extract candidate
    ↓
human review
    ↓
validate
    ↓
skills/local/
```

흐름을 사용한다.

---

# 27. Labs

Forge는 특정 기능 하나로 좁히지 않는다.
실험적 기능은 `labs/`에서 검증한다.

## 27.1 Opportunity Finder

목적:

여러 Skill을 창의적으로 조합하여
“이 조합이 어떤 반복 업무/제품을 만들 수 있는가?”를 탐색.

예:

```text
Ads API
+ Analytics
+ anomaly detection
+ LLM report
+ Slack
→ 광고대행사용 자동 이상탐지 Agent
```

평가 dimension:

- 대상 사용자
- 반복 문제
- 사용 빈도
- 구현 난이도
- external data 필요성
- 경쟁상품
- monetization 가능성
- defensibility

LLM 생성 아이디어와 실제 시장 검증은 구분한다.

---

## 27.2 Repo Auditor

GitHub/local repository를 읽고:

```text
이 repo가 production readiness에서 무엇이 부족한가?
```

를 판단하고 관련 Skill을 연결.

---

## 27.3 Agent Benchmark

같은 Skill/Task를 여러 Agent adapter에 실행하여:

- 성공 여부
- 테스트 통과
- latency
- token/cost
- diff size
- regressions

를 비교.

초기에는 구현하지 않는다.

---

## 27.4 Skill Graph

Skill ecosystem을 관계 그래프로 탐색.

---

# 28. 미래 Web Explorer

CLI가 안정된 뒤 `apps/web` 추가.

웹은 다음 UX를 목표로 한다.

## 검색

```text
search box
filters
collections
official
security
license
source
```

## Skill detail

```text
name
description
source
install count
version history
hash
security audit
license
SKILL.md
file tree
similar skills
used with
add to collection
compose
pin to project
```

## Compare

2~4개 Skill side-by-side.

## Playground

Skill 여러 개 선택 → composition 생성.

## Project

Local/connected project context → recommendations.

초기 웹 구현 때문에 CLI/core 설계를 왜곡하지 않는다.

---

# 29. CLI Command 장기 목표

```text
forge doctor
forge status

forge sync
forge sync --metadata-only
forge sync --source skills-sh
forge sync --changed-only

forge search "<query>"
forge inspect <skill-id>

forge collection create <name>
forge collection add <name> <skill-id>
forge collection list

forge scan [project-path]
forge recommend [project-path]

forge pin <skill-id> [--project ...]
forge unpin <skill-id>
forge outdated

forge compose create <name>
forge compose add <name> <skill-id>
forge compose analyze <name> --goal "..."

forge use <skill-id>
forge bundle <composition>

forge audit [project-path]

forge learn [project-path]
```

이 전체를 초기 release에 다 구현하지 않는다.

---

# 30. 첫 번째 수직 슬라이스

**첫 Codex 작업의 핵심은 다음이다.**

```text
Project Scanner
+
Skill Registry Metadata Sync
+
Local Search
+
Inspect
```

즉:

```powershell
forge scan
forge sync --metadata-only
forge search "postgres production"
forge inspect <id>
```

가 실제로 작동해야 한다.

이 네 가지가 되면 Forge는 이미 쓸 수 있다.

---

# 31. 초기 구현 단계

## Phase 0 — Repository Bootstrap

완료 조건:

- root README
- AGENTS.md
- Python package setup
- CLI entrypoint
- tests
- lint/type/test commands
- `.gitignore`
- docs/decisions

작성할 ADR:

```text
ADR-001 Local-first SQLite registry
ADR-002 External Skills are data, not Git source
ADR-003 Immutable Skill versions + project lock
ADR-004 Deterministic core, optional LLM
ADR-005 Monorepo platform boundary
```

---

## Phase 1 — Existing README Collector → Project Scanner v0

작업:

1. `C:\dev`에서 기존 collector 찾기
2. 동작 분석
3. regression fixture 작성
4. scanner module로 port
5. `forge scan` 구현
6. `.forge/project.json` 생성
7. secret exclusion test

Acceptance:

```powershell
cd C:\dev\stockback
forge scan
```

후 `.forge/project.json`이 생성된다.

그리고 최소한:

- Python
- project name
- README
- test command
- domain hints

가 들어간다.

---

## Phase 2 — Registry + skills.sh Metadata Sync

작업:

- SQLite migration
- SourceAdapter
- skills.sh adapter
- pagination
- resume
- retry/backoff
- rate limit
- metadata upsert
- sync stats

Acceptance:

```powershell
forge sync --source skills-sh --metadata-only
```

중단 후 다시 실행해도 이어서 동작한다.

동일 데이터를 다시 받아도 중복 row가 폭증하지 않는다.

---

## Phase 3 — Search + Inspect

작업:

- FTS5
- local search
- ranking
- inspect metadata
- on-demand detail fetch
- hash/version 저장
- file tree cache

Acceptance:

```powershell
forge search "postgres production"
```

이 관련 결과를 반환.

```powershell
forge inspect <id>
```

이 Skill metadata와 `SKILL.md`를 보여준다.

inspect만으로 script가 실행되지 않는다.

---

# 32. 두 번째 수직 슬라이스

Phase 4:

```text
scan
    ↓
recommend
    ↓
inspect
    ↓
pin
```

## Project recommendation

초기 추천 알고리즘은 deterministic feature 기반이어도 된다.

예:

```text
project contains Supabase
    → database / RLS / postgres skills boost

project has payments
    → payment/security/idempotency boost

project has Playwright gap
    → e2e/testing boost
```

그 후 optional semantic/LLM enrichment.

Acceptance:

```powershell
cd C:\dev\grit-business-diagnostic
forge recommend
```

이 프로젝트 증거와 함께 추천 이유를 출력.

---

# 33. 세 번째 수직 슬라이스

Phase 5:

```text
search
    ↓
favorite/collection
    ↓
compose
    ↓
composition manifest
```

Skill을 가지고 노는 경험을 먼저 만든다.

이것이 Forge 정체성에서 매우 중요하다.

---

# 34. 네 번째 수직 슬라이스

Phase 6:

- audit import
- license enrichment
- static checks
- version diff
- update available
- pin/lock/outdated

---

# 35. 다섯 번째 수직 슬라이스

Phase 7:

- generic agent bundle
- Codex adapter
- project `forge use`
- audit/recommend/apply loop

---

# 36. 그 이후

Phase 8:

- Web Explorer

Phase 9:

- Skill Graph
- Repo Auditor

Phase 10:

- Local Skill extraction
- Opportunity Finder
- Agent Benchmark

---

# 37. Logging / Observability

대규모 sync를 디버깅할 수 있어야 한다.

최소 로그:

```text
sync run id
source
page/cursor
request count
success/error count
429 count
retry count
skills discovered
skills inserted
skills updated
versions created
details fetched
duration
```

사용자가 CLI에서 너무 많은 raw debug를 보지 않도록:

```text
normal progress
--verbose
--debug
```

단계를 둔다.

---

# 38. 데이터 크기/성능 원칙

초기 수만 개 Skill metadata는 SQLite로 충분한 규모로 본다.

성능 문제를 추측해서 Elasticsearch, Kafka, Kubernetes, cloud vector DB 등을 선제 도입하지 않는다.

실측 후 확장한다.

---

# 39. 네트워크 비용 원칙

매 실행 시 모든 Skill detail을 다시 fetch하면 안 된다.

```text
metadata sync
    ↓
hash/status comparison
    ↓
changed/new/selected only detail processing
```

을 유지한다.

---

# 40. LLM 비용 원칙

수천 개 Skill 전체를 매 sync마다 LLM으로 평가하지 않는다.

```text
new skill
changed skill
explicit user request
selected/high-value subset
```

에만 LLM enrichment를 쓴다.

---

# 41. Embedding 원칙

embedding도 매 검색마다 재생성하지 않는다.

```text
new/changed text
    → embed once
```

embedding model/provider를 core schema에 강하게 종속시키지 않는다.

---

# 42. Tests

최소:

## unit

- ID parsing
- hash/version
- path validation
- scanner exclusion
- FTS ranking helper
- lockfile serialization

## contract

- skills.sh sample payload adapter
- rate limit/retry
- pagination
- detail/hash parsing

외부 API 실호출에만 의존하지 말고 recorded fixture를 둔다.

## integration

- temp SQLite
- sync fixture
- search
- detail cache
- project scan

## regression

기존 README Collector의 중요한 기존 동작.

---

# 43. 테스트 fixture에서 보안 주의

실제 프로젝트의:

- credentials
- `.env`
- user data
- private business data

를 fixture에 복사하지 않는다.

구조만 닮은 synthetic fixture를 만든다.

---

# 44. Error handling

CLI 에러는 사용자가 다음 행동을 알 수 있게 한다.

좋지 않은 예:

```text
HTTPError
```

좋은 예:

```text
skills.sh returned 401.
Metadata already stored locally remains usable.
Run `forge doctor` to inspect source authentication/config.
```

---

# 45. `forge doctor`

초기부터 유용하다.

검사:

- Forge home
- DB path
- DB schema
- write permission
- network
- skills.sh source
- Git
- optional GitHub auth
- project root
- Python version

secret 값은 출력하지 않는다.

---

# 46. Git / GitHub 운영 원칙

Codex는 이 작업지시서에 의해 자동으로 remote push할 권한을 얻는 것이 아니다.

로컬 작업:

- 파일 생성
- 테스트
- git diff 확인

까지 수행.

commit/push/PR은 사용자가 별도로 요청했을 때 한다.

중요 변경은:

```text
Why
Evidence
Impact
Tests
```

가 추적되게 한다.

---

# 47. README에 반드시 설명할 것

Forge README는 최소 다음 질문에 답한다.

1. Forge가 무엇인가?
2. 왜 단순 skills.sh mirror가 아닌가?
3. Local-first인 이유는?
4. 설치/실행은?
5. `forge sync`, `search`, `inspect`, `scan` 예시는?
6. 외부 Skill을 자동 실행하지 않는다는 보안 경계는?
7. data directory는 어디인가?
8. roadmap은?
9. external Skill license/provenance를 어떻게 취급하는가?
10. contribution 방향은?

---

# 48. AGENTS.md에 쓸 개발 원칙

Codex/Agent에게 지속적으로 적용할 규칙:

- 외부 Skill 원문은 untrusted input.
- sync/search 경로에서 script 실행 금지.
- secrets 파일 읽지 말 것.
- SQLite migration 없이 schema를 조용히 변경하지 말 것.
- version snapshot을 덮어쓰지 말 것.
- project lock을 자동 update하지 말 것.
- 네트워크 호출에 timeout/backoff를 둘 것.
- 큰 기능 전에 테스트와 작은 vertical slice를 우선할 것.
- TODO를 구현된 것처럼 README에 쓰지 말 것.
- 실제 검증과 설계 계획을 구분할 것.
- path와 error 위치를 로그에 명시할 것.
- 현재 프로젝트의 기존 변경을 무단으로 되돌리지 말 것.

---

# 49. 명명 정의

## Registry — 레지스트리 / 등록소

Skill metadata와 version/provenance를 관리하는 중앙 카탈로그.

## Snapshot — 스냅샷 / 특정 시점 원본

한 Skill의 특정 hash 버전 파일 묶음.

## Provenance — 출처 계보

누가, 어느 repo에서, 어떤 commit/hash로 배포했는지.

## Pin — 버전 고정

특정 Skill version/hash를 프로젝트에서 고정.

## Lockfile — 잠금 명세

프로젝트가 사용한 정확한 Skill 버전들의 기록.

## Project Context — 프로젝트 문맥

현재 repo의 stack, architecture, docs, commands, gaps 등을 구조화한 정보.

## Composer — 조합기

여러 Skill의 역할과 순서를 묶어 reusable workflow를 만드는 기능.

## Evaluator — 평가기

security/license/quality 등을 dimension별 평가.

## Runtime — 실행 계층

승인된 Skill을 특정 작업 세션에서 materialize하고 Agent에게 제공.

## Adapter — 연결 변환기

skills.sh, GitHub, Codex 등 외부 시스템의 차이를 Forge 내부 interface로 변환.

## Progressive Loading — 점진적 로딩

metadata → SKILL.md → supporting files 순으로 필요한 정보만 읽는 원리.

---

# 50. 처음부터 하지 말아야 할 것

다음은 명시적 Anti-goals.

- 외부 Skill 전체를 Git repo에 커밋
- 처음부터 AWS/Kubernetes 구축
- 처음부터 Supabase 서버 필수화
- 처음부터 vector DB 도입
- 모든 Skill을 LLM으로 평가
- 모든 upstream repo를 매 sync마다 git clone
- 자동 script 실행
- 자동 project update
- 10개 UI를 만들고 core CLI가 작동하지 않는 상태
- 20개 package를 빈 껍데기로만 생성
- “AI 점수” 하나로 quality/security를 숨김
- 공개 GitHub라는 이유로 license 무시
- README Collector 원본을 검증 없이 삭제

---

# 51. 초기 UX 목표

사용자가 가장 먼저 느껴야 할 가치는 다음이다.

## A. 아무 때나 스킬 찾기

```powershell
forge search "market microstructure"
```

## B. 마음에 드는 스킬 구경하기

```powershell
forge inspect <id>
```

## C. 현재 프로젝트에서 필요한 것 찾기

```powershell
cd C:\dev\stockback
forge scan
forge recommend
```

## D. 좋은 스킬 묶어두기

```powershell
forge collection ...
```

## E. 조합해서 놀기

```powershell
forge compose ...
```

이 경험이 Forge의 핵심이다.

---

# 52. 첫 Codex 세션의 구체 작업 목록

아래 순서로 진행한다.

## Step 1 — 현재 상태 확인

- `C:\dev\forge` 확인
- Git status 확인
- remote 확인
- repository가 초기 상태인지 확인
- 사용자 기존 파일이 있다면 덮어쓰지 않음

## Step 2 — 기존 README Collector 찾기

- `C:\dev` 조사
- 후보 폴더 나열
- 실제 collector 기능 확인
- 원본 보존

## Step 3 — 최소 repository bootstrap

생성:

```text
README.md
AGENTS.md
pyproject.toml
.gitignore
apps/cli/
packages/core/
packages/registry/
packages/sources/
packages/search/
packages/project/
docs/decisions/
tests/
```

아직 사용하지 않는 compose/evaluate/runtime/labs는 디렉터리를 남발하지 않아도 된다.
README architecture에는 미래 경계를 기록한다.

## Step 4 — CLI skeleton

최소:

```text
forge doctor
forge scan
forge sync
forge search
forge inspect
```

subcommand가 뜨게 한다.

## Step 5 — Project Scanner v0

기존 Collector 기능을 흡수.

## Step 6 — SQLite registry

migration 포함.

## Step 7 — skills.sh source adapter

metadata-only sync부터.

## Step 8 — FTS search

## Step 9 — on-demand inspect/detail cache

## Step 10 — test

## Step 11 — README 갱신

실제로 구현한 것만 완료라고 기록.

## Step 12 — final report

Codex가 사용자에게 다음을 보고:

```text
구현한 것
실행 명령
테스트 결과
주요 파일 경로
남은 Phase
위험/미결정
```

---

# 53. 초기 완료 정의 (MVP-0)

다음이 모두 되면 첫 milestone 완료.

```powershell
cd C:\dev\forge

forge doctor

forge sync --source skills-sh --metadata-only

forge search "postgres production"

forge inspect <valid-skill-id>

cd C:\dev\stockback

forge scan

forge recommend
```

단 `forge recommend`는 Phase 4라면 다음 milestone로 미뤄도 된다.

최소 첫 milestone은:

```text
scan + sync + search + inspect
```

이다.

---

# 54. 초기 품질 게이트

완료라고 말하기 전에:

- type/lint
- unit tests
- integration tests
- `git diff --check`
- secret scan/basic check
- README command 실제 실행
- Windows PowerShell path 테스트

를 한다.

Windows가 현재 주 사용환경이므로 POSIX path만 테스트하고 끝내지 않는다.

---

# 55. 장기 성공 기준

Forge의 성공은 “Skill을 많이 다운로드했다”가 아니다.

장기적으로 다음 질문에 Yes라고 답할 수 있어야 한다.

1. 새로운 Skill을 빠르게 발견할 수 있는가?
2. upstream 변경을 안전하게 감지할 수 있는가?
3. 과거 버전을 재현할 수 있는가?
4. Skill의 출처와 license를 알 수 있는가?
5. 위험한 Skill을 그대로 실행하지 않는가?
6. 현재 프로젝트에 왜 이 Skill이 필요한지 설명할 수 있는가?
7. Skill 여러 개를 조합해 새로운 workflow를 만들 수 있는가?
8. 실제 프로젝트 경험이 다시 reusable knowledge가 되는가?
9. 특정 Agent/Cloud에 종속되지 않는가?
10. CLI만으로도 충분히 유용하고, 이후 Web/Labs로 확장 가능한가?

---

# 56. 최종 아키텍처 그림

```text
                     External Skill Ecosystem
                  /             |              \
             skills.sh        GitHub          Local
                  \             |              /
                   \            |             /
                    ┌────────────────────────┐
                    │     Source Adapters     │
                    └───────────┬────────────┘
                                │
                         metadata / files
                                │
                                ▼
                    ┌────────────────────────┐
                    │   Versioned Registry    │
                    │ SQLite + Snapshots      │
                    └───────────┬────────────┘
                                │
             ┌──────────────────┼──────────────────┐
             │                  │                  │
             ▼                  ▼                  ▼
          Search             Evaluator          Collections
             │                  │                  │
             └──────────────────┼──────────────────┘
                                │
                                ▼
                         Skill Explorer
                                │
                      ┌─────────┴─────────┐
                      ▼                   ▼
                   Composer           Project Layer
                      │                   │
               Playground/Labs       Project Scanner
                      │                   │
                Opportunity           Recommender
                      │                   │
                      └─────────┬─────────┘
                                ▼
                         Runtime / Bundle
                                │
                    ┌───────────┼────────────┐
                    ▼           ▼            ▼
                  Codex       Claude       Others
                                │
                                ▼
                         Current Project
                                │
                                ▼
                         Test / Audit / Diff
                                │
                                ▼
                       Reusable Local Skill
```

---

# 57. 가장 중요한 마지막 원칙

Forge를 단순 다운로드 매니저로 축소하지 않는다.

또한 처음부터 거대한 autonomous agent platform을 만들지도 않는다.

정확한 방향은:

> **먼저 좋은 지식을 손안에 넣고(search/inspect),  
> 그 지식을 안전하게 최신 상태로 유지하고(sync/version),  
> 마음껏 분류하고 조합해보고(collection/compose/play),  
> 필요할 때 현재 프로젝트에 정확히 연결하고(scan/recommend/pin/use),  
> 실제 프로젝트에서 얻은 경험을 다시 자산으로 환원한다(learn).**

이 흐름이 Forge의 제품 철학이다.

---

# 58. Codex의 구현 태도

- 기존 사용자 작업을 존중한다.
- 실제 코드를 먼저 읽고 문서를 수정한다.
- 모르는 것을 구현됐다고 가정하지 않는다.
- 외부 API contract는 adapter 경계 안에 둔다.
- 실패/재시도/중단 복구를 first-class로 설계한다.
- 초기에는 복잡한 추상화보다 명확한 책임 경계를 우선한다.
- 테스트를 통과하지 않은 기능은 완료로 기록하지 않는다.
- 장기 아키텍처를 핑계로 MVP를 늦추지 않는다.
- MVP를 핑계로 provenance/version/security 경계를 깨지 않는다.

---

# 59. 작업 시작 명령의 의도

사용자가 이 파일을 Codex에 넘긴 뒤 원하는 행동은 대략 다음과 같다.

```text
1. C:\dev\forge를 실제로 검사한다.
2. C:\dev 아래 기존 README Collector를 찾는다.
3. 위 불변조건에 맞춰 Forge monorepo의 최소 구조를 잡는다.
4. 기존 Collector를 안전하게 Project Scanner로 흡수한다.
5. scan + skills.sh metadata sync + local search + inspect를 첫 수직 슬라이스로 완성한다.
6. 테스트와 문서를 갱신한다.
7. commit/push는 사용자가 별도로 지시하기 전에는 하지 않는다.
8. 이후 recommend → pin → compose/play → evaluator → agent adapter → web/labs 순으로 확장 가능한 경계를 유지한다.
```

이 문서를 구현 과정에서 살아 있는 기준 문서로 사용한다.
아키텍처가 실제 구현과 달라지면 조용히 무시하지 말고 ADR과 이 문서를 함께 갱신한다.
