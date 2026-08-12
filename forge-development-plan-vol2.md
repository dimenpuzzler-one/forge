# Forge 개발기획 Vol.2
## Procedural Intelligence, Adaptive Skill Composition, Evidence-Based Learning, and Recursive Dogfooding

> **문서 목적**  
> 이 문서는 Forge의 1차 구현 경험과 ORACROSS Growth-oriented Visual Redesign dogfooding 결과를 바탕으로, Forge가 단순한 Skill 수집/검색 도구를 넘어 **“어떻게 일해야 하는가”를 검색·판단·구성·실행·검증·학습하는 Personal Engineering OS / Procedural Intelligence Layer**로 진화하기 위한 Vol.2 개발 기획서다.
>
> 기능 목록만 나열하지 않는다. **제품 철학, 운영 원칙, LLM과 deterministic core의 역할 분리, adaptive skill composition, report/learning, GitHub 지식 축적, recursive dogfooding, README/문서화 원칙, 구현 로드맵**까지 하나의 설계로 묶는다.
>
> **기준일:** 2026-08-12  
> **대표 dogfooding case:** ORACROSS Growth-oriented Visual Redesign  
> **Forge session:** `session-8b7b45eed05e4874a954c9d823ff149d`

---

# 0. Executive Summary

Forge Vol.1에서 확인한 것은 분명하다.

Forge는 이미 외부 Skill을 동기화하고, 검색하고, inspect/audit하고, pin하고, composition을 만들고, immutable session bundle로 materialize하여 agent가 읽게 하는 기반을 갖추기 시작했다.

하지만 ORACROSS에서 실제로 Forge를 사용해 보니 사용자가 다음을 너무 많이 직접 해야 했다.

```text
goal
→ 검색어를 사람이 생각
→ forge search 반복
→ 후보를 사람이 비교
→ inspect 반복
→ audit 반복
→ pin 반복
→ compose create/add 반복
→ bundle 생성
→ 긴 agent 지시문 작성
→ agent 실행
→ 결과 검증
→ Skill 기여도 판단
→ report / learning을 다시 요청
```

이 과정은 Forge primitives를 검증하기 위한 dogfooding으로는 필요했다. 그러나 최종 UX는 아니다.

Vol.2의 목표는 이 과정을 다음 폐루프로 바꾸는 것이다.

```text
UNDERSTAND
Project + Goal 이해
        ↓
PLAN
Task decomposition
        ↓
RETRIEVE
관련 Skill 후보 검색
        ↓
JUDGE
LLM semantic evaluation / role assignment
        ↓
VERIFY
Forge provenance / security / version / policy gate
        ↓
COMPOSE
검증된 Skill + 탐색 Skill 구성
        ↓
BRIEF
Agent 실행 지시문 자동 생성
        ↓
EXECUTE
Codex / Claude / Gemini / future agent
        ↓
VERIFY
tests / browser / build / evidence
        ↓
FINALIZE
usage report / provenance / artifacts
        ↓
LEARN
project memory / global learning candidates
        ↓
CURATE
일반화 / 비밀정보 제거 / 중복 제거
        ↓
PUBLISH
Forge knowledge PR
        ↓
NEXT PLAN
과거 증거가 다음 판단의 입력이 됨
```

Vol.2의 가장 중요한 원칙은 두 문장으로 요약한다.

> **LLM은 의미를 판단하고, Forge는 사실·증거·정책·버전을 강제한다.**

> **Forge는 코드를 기억하는 시스템이 아니라, “어떻게 일했고 무엇이 실제로 효과가 있었는가”를 기억하는 시스템이다.**

---

# 1. Forge가 해결하려는 진짜 문제

AI coding workflow는 보통 다음과 같다.

```text
prompt
→ model / agent
→ code
```

조금 발전하면:

```text
repo context + RAG + prompt
→ agent
→ code
```

하지만 여기에는 여전히 빈 공간이 있다.

- 이 작업에 어떤 전문 절차가 필요한가?
- 어떤 Skill이 적절한가?
- 어떤 Skill은 중복되는가?
- 어떤 Skill은 위험한가?
- 어떤 순서로 적용해야 하는가?
- 기존 프로젝트에서는 무엇이 잘 작동했는가?
- 어떤 판단이 사실이고 어떤 판단이 추론인가?
- 작업 후 무엇을 배웠는가?
- 다음에는 어떤 Skill을 빼거나 새로 시도해야 하는가?

Forge는 이 빈 공간을 담당한다.

RAG가 주로 “무엇을 알고 있는가?”를 검색한다면, Forge는 다음을 다룬다.

```text
How should we act?
What worked before?
Which procedure should we apply now?
Which expert capability should be added or removed?
```

따라서 Forge는 **Procedural Context Layer**이며 장기적으로는 **Procedural Intelligence / Engineering Memory Layer**다.

---

# 2. Forge의 제품 정체성

Forge를 단순 Skill manager로 정의하지 않는다.

> **Forge is a procedural intelligence and engineering memory layer above AI agents.**

한국어 정의:

> Forge는 AI agent 위에서 프로젝트의 목표를 이해하고, 필요한 작업 절차와 전문 Skill을 찾고, 조합하고, 실행에 전달하고, 결과를 검증하고, 그 경험을 다음 작업에 재사용하는 절차적 지능 시스템이다.

Forge의 핵심 자산은 Skill 개수 자체가 아니다.

시간이 지나며 다음이 쌓여야 한다.

```text
Skill Catalog
+
Skill Graph
+
Project Memory
+
Execution Cases
+
Verification Evidence
+
Composition History
+
Human Feedback
+
Procedural Patterns
```

결국 Forge는 **어떤 문제에서 어떤 절차와 어떤 전문성이 실제로 효과가 있었는지를 축적하는 engineering experience graph**로 발전할 수 있다.

---

# 3. 핵심 개발 철학

## 3.1 External Skill은 untrusted supply-chain input이다

외부 Skill은 유용한 절차적 지식이지만 기본적으로 신뢰하지 않는다.

모든 외부 Skill은 최소한 다음을 가진다.

- source / repository
- author / publisher
- version / revision
- content hash
- fetched timestamp
- license
- static audit
- external audit results
- trust state
- local evaluation history

기본 trust lifecycle:

```text
quarantined
→ imported
→ reviewed
→ validated
→ trusted / pinned
→ local-owned
```

원칙:

- update detection은 자동일 수 있다.
- update adoption은 명시적이어야 한다.
- 외부 script는 기본적으로 자동 실행하지 않는다.
- bundle에 들어간 Skill은 immutable snapshot이어야 한다.
- 인기와 install count는 안전성 또는 적합성의 증거가 아니다.

## 3.2 LLM은 판단하고 deterministic core가 허가한다

LLM이 잘하는 것:

- 사용자 목표 해석
- task decomposition
- semantic relevance 판단
- Skill 역할 추정
- 후보 중복/보완 판단
- workflow 설계
- 실행 brief 생성
- 결과 해석
- learning candidate 추출

Forge core가 맡을 것:

- 실제 Skill 존재 여부
- exact hash/version
- provenance
- trust state
- audit
- policy
- secret/security boundary
- project lockfile
- bundle materialization
- verification result
- artifact persistence

따라서:

```text
LLM:
“이 작업에는 copywriting + page-cro + frontend-design이 필요하다.”

Forge:
“실제 존재하는가?”
“현재 hash는?”
“audit는?”
“policy를 통과하는가?”
“과거 evidence는?”
“중복 Skill은?”
```

LLM의 답은 **proposal**이다. Forge가 evidence와 policy로 승인해야 한다.

## 3.3 Evidence before memory

Forge가 잘못된 자기확신을 학습하면 시스템 전체가 오염된다.

모든 learning은 evidence class를 가진다.

### Observed
직접 확인된 사실.

- code diff
- test/build result
- browser route result
- screenshot
- viewport overflow
- changed files
- final runtime state
- human explicit acceptance/rejection
- revert 여부

### Inferred
agent/LLM의 해석.

- “이 Skill이 copy input을 개선했다.”
- “새 identity가 더 강하다.”
- “이 composition 순서가 더 효과적이다.”

### Human-required
실제 사용자/production data가 필요한 주장.

- conversion 향상
- 디자인 선호
- 고객 이해도
- 브랜드 효과

원칙:

```text
Observed > Inferred
Human validated > Agent self-evaluation
```

> Inferred는 hypothesis로 저장할 수 있지만 global truth로 자동 승격하면 안 된다.

## 3.4 Raw memory와 curated knowledge를 분리한다

### Layer 1 — Raw Operational Memory
`~/.forge/`

- sessions
- full reports
- screenshots
- raw logs
- exact local paths
- project-specific evidence

질문: **실제로 무슨 일이 있었는가?**

### Layer 2 — Project Memory

예: ORACROSS-specific experience.

- 현재 visual language
- local constraints
- local Skill candidates
- project-specific patterns

질문: **이 프로젝트에서는 무엇이 먹혔는가?**

### Layer 3 — Curated Forge Knowledge

Forge GitHub repo의 정제된 지식.

- cases
- patterns
- skill notes
- experiments

질문: **다른 프로젝트에도 재사용할 가치가 있는 것은 무엇인가?**

Raw memory를 그대로 GitHub에 올리지 않는다.

## 3.5 Exploration vs Exploitation

과거에 점수가 좋았던 Skill만 반복하면 Forge는 local optimum에 갇힌다.

새 Skill은 계속 등장하고 기존 Skill보다 좋을 수 있다.

따라서 composition에는 **exploration budget**이 필요하다.

```text
Trusted / Proven Skills
+
Exploration Candidates
=
Adaptive Composition
```

예:

| Task risk | Proven | Exploration |
|---|---:|---:|
| UI / copy / analysis | 70~85% | 15~30% |
| 일반 application code | 80~90% | 10~20% |
| auth / payment / security | 95~100% | 0~5% |
| destructive DB migration | ~100% | 기본 0% |

새 Skill을 넣을 때 기록:

- 왜 실험하는가?
- 기존 Skill과 무엇이 다른가?
- 어떤 improvement를 기대하는가?
- 실제 기여했는가?
- 다음에는 core로 승격할 것인가?

## 3.6 특정 agent에 종속되지 않는다

```text
               Forge
                 │
      ┌──────────┼──────────┐
      │          │          │
    Codex     Claude      Gemini
      │          │          │
   future adapters...
```

Forge의 핵심 output은 먼저 agent-neutral execution plan이어야 한다. Adapter가 각 agent에 맞게 전달한다.

## 3.7 Forge는 Forge에도 적용된다

```text
Forge repo
↓
forge plan "recommendation 품질 개선"
↓
Skill selection
↓
composition
↓
agent implementation
↓
tests
↓
Forge usage report
↓
Forge learning
↓
next Forge plan
```

단, 재귀적 사용에는 보호 계층이 필요하다.

### Level 0 — Protected Core Policy
- trust model
- secret handling
- credential policy
- destructive-operation policy
- learning evidence rules
- auto-publish policy

### Level 1 — Planner / Retrieval / Composition
적극적 dogfooding 가능.

### Level 2 — Application / CLI / UX
일반 dogfooding 대상.

Level 0 변경은 human approval을 기본으로 한다.

---

# 4. ORACROSS Dogfooding Case

## 4.1 Task

**Task ID:** `2026-08-12-growth-visual-redesign`

목표:

- positioning
- conversion copy
- visual identity
- responsive quality
- accessibility

보호 범위:

- business logic
- deterministic calculation
- AI facts/rules/generation pipeline
- Supabase / RLS / RPC
- entitlement / payment / coupon
- data contracts
- route behavior

## 4.2 Composition

```text
positioning
→ copy
→ conversion
→ design-direction
→ component-architecture
→ responsive
→ accessibility
```

사용 Skill:

1. `coreyhaines31/marketingskills/product-marketing-context`
2. `coreyhaines31/marketingskills/copywriting`
3. `coreyhaines31/marketingskills/page-cro`
4. `anthropics/skills/frontend-design`
5. `vercel-labs/agent-skills/vercel-composition-patterns`
6. `wshobson/agents/responsive-design`
7. `addyosmani/web-quality-skills/accessibility`

## 4.3 실제 기여도

| Skill | Contribution |
|---|---|
| product-marketing-context | High |
| copywriting | Medium |
| page-cro | High |
| frontend-design | High |
| vercel-composition-patterns | Low |
| responsive-design | Medium |
| accessibility | Medium |

핵심 학습:

> Composition은 “좋은 Skill을 최대한 많이 넣는 것”이 아니다.

이번 task에서는 component architecture Skill이 guardrail 역할은 했지만 visible contribution은 낮았다.

따라서 다음 유사 task에서는:

```text
component API / reusable state composition 변경이 있을 때만
→ composition-patterns 선택
```

하는 conditional rule이 합리적이다.

## 4.4 Applied Patterns

### Positioning context before copy

```text
known / inferred / unknown
↓
허용 가능한 claim
↓
copy
```

가짜 testimonial, 존재하지 않는 metric, 검증되지 않은 경쟁 우위를 막는다.

### Benefit-first Hero + explicit CTA

결과 중심 headline과 사용자가 얻는 것을 명시한 CTA로 수렴한다.

### Methodology as trust

외부 proof가 없으면 proof를 만들지 않는다.

대신 검증 가능한 mechanism을 보여준다.

```text
Calculate
→ Compare
→ Explain
```

### Frontend design drives identity

`frontend-design`이 Crossing Signals visual language를 주도했다.

Responsive와 Accessibility는 visual ambition을 제거하는 것이 아니라 **quality floor** 역할을 했다.

## 4.5 Verification

Observed:

- `pnpm typecheck` pass
- `pnpm test` pass
- `pnpm build` pass
- `git diff --check` pass
- 320/375/390/430px no horizontal overflow
- CTA `/calculator` route 확인
- semantic spot check
- before/after screenshot

Human-required:

- real conversion uplift
- visitor preference
- authenticated report E2E
- payment E2E
- full screen-reader audit

이 구분을 future learning model의 기본 규칙으로 사용한다.

---

# 5. Low-level primitives와 High-level UX

현재 command는 plumbing으로 유지한다.

```text
scan
sync
search
inspect
audit-skill
outdated
diff
recommend
pin
compose
bundle
use
```

삭제하지 않는다.

그 위에 high-level porcelain을 만든다.

```text
plan
run
finalize
report
learn
cases
```

Git이 low-level object command를 유지하면서 사용자는 `git commit`을 쓰는 것과 같은 구조다.

---

# 6. Target UX

최종적으로 사용자는 다음 정도만 입력해야 한다.

```powershell
forge plan "ORACROSS 랜딩을 전환 중심으로 재설계"
```

Planner output 예:

```text
Goal
...

Task decomposition
1. positioning
2. copy
3. CRO
4. visual identity
5. responsive
6. accessibility

Selected
- product-marketing-context
- copywriting
- page-cro
- frontend-design
- responsive-design
- accessibility

Exploration
- new-skill-X

Excluded
- composition-patterns
  reason: component API/state change not expected

Past evidence
- ORACROSS growth redesign:
  page-cro high
  frontend-design high
  composition-patterns low
```

그다음:

```powershell
forge run
```

또는:

```powershell
forge run "<goal>" --auto
```

종료:

```text
✓ Task completed
✓ Verification passed
✓ Usage report generated
✓ Project memory updated
✓ Learning candidates captured
✓ Exploration Skill evaluated
✓ Curated knowledge candidate prepared
```

---

# 7. Vol.2 Architecture

```text
User Goal
↓
Project Understanding
↓
Planner
↓
Retriever
↓
LLM Reranker
↓
Policy / Audit Gate
↓
Adaptive Composer
↓
Brief Compiler
↓
Agent Adapter
↓
Execution
↓
Verification Aggregator
↓
Finalizer
↓
Learning Ingestor
↓
Curator
↓
Knowledge Publisher
```


---

# 8. Planner

## 입력

- user goal
- project context
- `.forge/project.json`
- `.forge/skills.lock`
- repository signals
- Forge registry
- project memory
- similar cases
- Skill usage history
- trust policy
- risk profile

## 전체 catalog를 LLM에 넣지 않는다

```text
9,610 Skills
↓
FTS / metadata filter
50~100 candidates
↓
LLM rerank
10~20 candidates
↓
audit / trust / overlap / history
5~10 selected
```

장기적으로:

```text
FTS
+
vector similarity
+
skill graph
+
historical performance
```

hybrid retrieval로 확장한다.

## Task decomposition

Goal을 role로 분해한다.

예:

```text
public landing conversion redesign
```

↓

```text
positioning
copy
conversion
visual identity
responsive
accessibility
```

Role taxonomy는 기본값을 제공하되 완전히 고정하지 않는다. LLM이 task-specific role을 제안할 수 있어야 한다.

## Selection / Exclusion reason

모든 추천에는 이유를 저장한다.

```json
{
  "skill": "page-cro",
  "role": "conversion",
  "selected": true,
  "reason": "Public conversion route with CTA/trust sequencing",
  "confidence": 0.92
}
```

제외도 기록한다.

```json
{
  "skill": "composition-patterns",
  "selected": false,
  "reason": "No reusable component API or state composition change expected"
}
```

제외 기록은 중요하다. 다음 planner가 “왜 지난번에 뺐는가?”를 설명할 수 있기 때문이다.

---

# 9. Adaptive Composition

Composition은 다음의 합이다.

```text
Required Skills
+
Proven Skills
+
Conditional Skills
+
Exploration Skills
```

Exploration candidate 기준:

- 현재 task relevance
- audit 통과
- trusted source
- 기존 core와 의미 있는 차이
- 최근 등장 또는 upstream 변화
- 과거 미사용
- 기존 Skill과 중복이 지나치지 않음

결과 lifecycle:

```text
exploratory
→ evaluated
→ validated
→ preferred
```

또는:

```text
exploratory
→ low contribution
→ conditional / rejected
```

기여도는 agent 자기평가 하나로 결정하지 않는다.

가능한 evidence:

- 실제 code impact
- test/build/browser result
- human feedback
- revert 여부
- overlap reduction
- repeated success
- production outcome

---

# 10. Composition Graph

Vol.1 composition은 role list에 가깝다.

Vol.2에서는 DAG metadata를 지원한다.

```text
product context
     ↓
copy
     ↓
CRO
     ↓
visual design
   ↙    ↘
responsive  accessibility
     ↓
verification
```

Edge:

- `requires`
- `consumes`
- `validates`
- `works_with`
- `alternative_to`
- `conflicts_with`
- `extends`
- `co_used`

이 graph는 단순한 UI 시각화가 아니라 planner의 실행 순서와 conditional selection을 결정하는 데이터가 되어야 한다.

---

# 11. Execution Brief Compiler

사용자가 긴 Codex 지시문을 직접 만들 필요가 없어야 한다.

Session structure:

```text
session/
  manifest.json
  project-context.json
  task.json
  plan.json
  composition.json
  execution-brief.md
  expected-evidence.json
  skills/
```

Execution brief 기본 구조:

1. Goal
2. Project context
3. Protected boundaries
4. Selected Skill team
5. Skill priority
6. Dependency/order
7. Required verification
8. Expected evidence
9. Forbidden assumptions
10. Completion schema

특히 중요한 형식:

> **Skill → principle → expected evidence**

예:

```text
page-cro
→ one primary outcome-specific CTA
→ implementation: landing CTA hierarchy
→ evidence expected: visible CTA + route click verification
```

이 구조가 있어야 사후에 “Skill을 읽었는가?”가 아니라 “실제로 원칙이 적용됐는가?”를 판단할 수 있다.

---

# 12. Agent Adapter

예:

```text
adapters/
  codex.py
  claude.py
  generic.py
```

Adapter 책임:

- execution brief 위치 전달
- bundle 위치 전달
- project path 전달
- permission scope 전달
- expected result artifact 위치 전달
- completion metadata 연결

Forge core는 agent-specific behavior를 최소한만 알아야 한다.

---

# 13. Verification Aggregator

Agent가 “완료했습니다”라고 말한 것과 실제 완료를 구분한다.

예:

```json
{
  "commands": [
    {"name": "typecheck", "status": "passed"},
    {"name": "test", "status": "passed"},
    {"name": "build", "status": "passed"}
  ],
  "notExecuted": [],
  "humanRequired": []
}
```

규칙:

- transient HMR error와 final-state error 구분
- `failed`, `not_executed`, `unavailable` 구분
- final terminal state 우선
- browser / screenshot / route 검증도 evidence로 저장
- 검증하지 않은 것을 pass로 간주하지 않음

ORACROSS에서는 개발 중 transient CSS import HMR 오류가 있었지만 이후 build가 정상 통과했다. 이 사례는 “historical dev log”와 “final-state blocker”를 구분해야 한다는 실제 근거가 된다.

---

# 14. Automatic Finalization

현재 ORACROSS에서는 별도 요청으로 report를 생성했다.

Vol.2에서는 `forge run` 종료 후 자동 실행한다.

내부 primitive:

```powershell
forge finalize <session-id>
```

생성:

```text
~/.forge/history/<project>/<task-id>/
  report.md
  task.json
  composition.json
  skill-evaluations.json
  applied-patterns.json
  verification.json
  learnings.json
```

ORACROSS artifact set을 최초 schema fixture로 활용한다.

Finalizer는 “리포트 문장 생성기”가 아니다.

책임:

- execution provenance 수집
- exact Skill/hash 기록
- changed files 연결
- verification 결과 정규화
- Skill → principle → implementation → evidence mapping
- learning candidate 추출
- evidence classification
- project provenance pointer 작성

---

# 15. Report Schema

## report.md

사람용.

필수:

1. Project / Task
2. Goal / Scope
3. Composition
4. Skill → principle → implementation → evidence
5. Applied patterns
6. Before / After
7. Verification
8. Observed / Inferred / Human-required
9. Skill evaluation
10. Composition learning
11. Local Skill candidates
12. Forge product feedback

## task.json

필수 후보:

- `schemaVersion`
- `taskId`
- `project`
- `repositoryRoot`
- `goal`
- timestamps
- session
- git
- completed scope
- untouched scope
- humanRequired
- report references

## composition.json

필수 후보:

- order
- roles
- selected Skills
- exact hash
- source
- trust
- selection reason
- exclusion reason
- expected contribution
- actual contribution
- conditional future rule
- exploration flag

## skill-evaluations.json

필수 후보:

- skill id
- role
- contribution
- confidence
- observed evidence
- inferred contribution
- redundancy
- conflicts
- future recommendation
- exploration result
- human feedback

## applied-patterns.json

장기적으로 가장 중요한 asset 중 하나다.

```json
{
  "name": "positioning-context-before-copy",
  "origin": [],
  "principle": "",
  "procedure": [],
  "appliedTo": [],
  "evidence": [],
  "generalizability": "candidate"
}
```

## learnings.json

반드시 분리:

```json
{
  "projectLocal": [],
  "globalCandidates": [],
  "hypotheses": [],
  "doNotClaim": []
}
```

---

# 16. Learning Ingestor

JSON이 생성됐다고 Forge가 학습한 것은 아니다.

```text
report artifacts
↓
Learning Ingestor
↓
forge.db
```

초기 DB 후보:

## tasks

- id
- project_id
- goal
- task_type
- session_id
- status
- timestamps

## task_skills

- task_id
- skill_id
- hash
- role
- selected_reason
- exploration
- trust_state

## skill_evaluations

- task_id
- skill_id
- contribution
- confidence
- evidence class
- overlap
- recommendation

## applied_patterns

- id
- name
- procedure
- source_task
- evidence_class
- project_specific
- generalization_status

## verification_evidence

- task_id
- type
- status
- details

## project_learnings

- project_id
- learning
- evidence_class
- confidence

## global_learning_candidates

- learning
- supporting_tasks
- evidence_class
- status

## human_feedback

- task_id
- target
- rating/decision
- note

## cases

- id
- project
- task_type
- summary
- published_path

---

# 17. Learning Weighting

하나의 `Skill score = 83` 같은 숫자로 모든 것을 압축하지 않는다.

분리해서 본다.

- relevance
- safety
- implementation contribution
- verification success
- human preference
- production outcome
- redundancy
- task-type fit

예:

```text
Agent: “very useful”
→ low weight

Build/test pass
→ strong technical evidence

Human accepted
→ strong preference evidence

Production metric improved
→ strong outcome evidence

Reverted
→ negative evidence
```

ORACROSS에서 `frontend-design`이 실제 CSS/SVG 변화를 만들었다는 것은 observed다. 반면 “사람들이 더 좋아할 것”은 human-required다. 이 둘을 같은 점수로 섞지 않는다.

---

# 18. Project Memory와 Global Learning

Project-local example:

```text
ORACROSS의 현재 visual language는 Crossing Signals다.
```

다른 프로젝트에 그대로 복사하면 안 된다.

Global candidate example:

```text
Public growth redesign에서 positioning context를 copy보다 먼저 확정하면 unsupported claim을 줄일 가능성이 있다.
```

한 번의 task로 global truth가 되지 않는다.

승격 조건 후보:

- 여러 다른 프로젝트
- 반복 observed evidence
- human feedback
- contradiction이 낮음
- 유사 task에서 재현

---

# 19. Case Library

CLI:

```powershell
forge cases
forge cases --project oracross
forge cases --skill frontend-design
forge cases --type visual-design
forge cases --after 2026-08-01
```

Planner는 case library도 retrieval input으로 사용한다.

Case는 코드 복사 대상이 아니라 **decision procedure evidence**다.

---

# 20. Skill Usage Intelligence

예:

```powershell
forge skills usage anthropics/skills/frontend-design
```

예상 output:

```text
Used: 14 tasks

High contribution: 9
Medium: 4
Low: 1

Common pairings:
- page-cro
- responsive-design
- accessibility

Strong task fit:
- landing redesign
- brand identity

Weak task fit:
- backend refactor

Status:
validated / preferred
```

과거 사용량이 많은 Skill을 무조건 추천하는 것이 아니라 task-type fit과 evidence를 같이 본다.

---

# 21. Curated GitHub Knowledge

`~/.forge`만 사용하면 local memory로 끝난다.

정제된 결과는 Forge GitHub repo에도 남길 가치가 있다.

그러나 **raw report를 그대로 push하지 않는다.**

금지:

- local absolute path
- token / secret
- customer data
- private project logic
- sensitive screenshot
- project-specific noise
- agent hallucination

Pipeline:

```text
Raw Report
↓
Learning Extraction
↓
Secret / Privacy Filter
↓
Generalization
↓
Deduplication
↓
Evidence Threshold
↓
Curated Knowledge Candidate
↓
GitHub PR
```

---

# 22. GitHub Knowledge Structure

```text
knowledge/
├─ cases/
│  └─ 2026/
│     └─ 2026-08-12-oracross-growth-redesign.md
├─ patterns/
│  ├─ positioning-before-copy.md
│  ├─ evidence-led-trust.md
│  └─ responsive-quality-floor.md
├─ skill-notes/
│  └─ frontend-design.md
└─ experiments/
   └─ compositions/
      └─ oracross-growth-ui.md
```

목적:

- development history가 남음
- planner behavior 변경의 근거가 남음
- 사람이 review 가능
- 다른 환경에서도 재사용 가능
- Forge 자체가 실제로 어떻게 성장했는지 추적 가능

---

# 23. Auto Push보다 Auto PR

초기에는 main direct push를 기본값으로 하지 않는다.

```text
finalize
↓
curate
↓
branch
↓
PR
↓
human review
↓
merge
```

예:

```text
forge/learning-2026-08-12-oracross-growth-redesign
```

PR 제목 예:

```text
learning: add ORACROSS growth redesign case
```

향후 다음 조건의 일부 knowledge만 auto-merge 검토:

```text
Observed
+ sanitized
+ no secrets
+ duplicate-safe
+ approved artifact type
```

Inferred 또는 Human-required가 포함되면 review 유지.

---

# 24. Knowledge Metadata

```yaml
date: 2026-08-12
project: ORACROSS
task: growth-visual-redesign

task_type:
  - product-marketing
  - conversion
  - visual-design

composition:
  proven: 6
  exploratory: 1

evidence:
  observed: 14
  inferred: 4
  human_required: 4

status:
  curated: true
  global_truth: false
```

날짜 / 프로젝트 / task / Skill은 future retrieval의 핵심 key다.

---

# 25. Recursive Forge-on-Forge

첫 recursive milestone 후보:

```text
forge run "Forge에 plan / finalize / learn / cases를 구현하라."
```

Forge가 자기 repo를 scan하고, Skill을 선택하고, agent가 구현하고, Forge가 검증하고, 자기 report와 learning을 남긴다.

이것이 성공하면 Forge의 철학이 실제 시스템 동작으로 연결된다.

---

# 26. Recursive Safety

Forge가 자기 보안정책을 편의상 완화할 수 없어야 한다.

나쁜 예:

```text
“security gate 때문에 작업이 막힘”
↓
자기 policy 완화
↓
위험 Skill 허용
```

방지:

- protected policy modules
- policy mutation human approval
- credential code elevated review
- learning schema migration review
- destructive DB migration explicit approval

> **Forge는 스스로 더 똑똑해질 수 있어야 하지만, 스스로 증거의 기준과 신뢰의 기준을 낮출 수는 없어야 한다.**


---

# 27. `forge plan` MVP

```powershell
forge plan "<goal>"
```

MVP scope:

1. project context load
2. goal decomposition
3. FTS top-K retrieval
4. LLM rerank
5. role assignment
6. provenance/audit/policy filtering
7. historical evidence lookup
8. exploit/explore selection
9. selection/exclusion reason
10. plan artifact 저장

저장:

```text
~/.forge/plans/<plan-id>/
  plan.json
  plan.md
```

`plan.md`는 사람이 읽는 설명이고 `plan.json`은 실행 가능한 정규화 데이터다.

---

# 28. `forge run` MVP

초기에는 agent execution을 완전히 자동화하지 않아도 된다.

첫 단계의 목표:

```text
plan
→ composition
→ bundle
→ execution brief
→ adapter handoff
```

agent 결과와 Forge session을 반드시 연결한다.

장기적으로는:

```powershell
forge run "<goal>" --agent codex
forge run "<goal>" --agent claude
```

같은 형태를 지원할 수 있다.

---

# 29. `forge finalize`

초기 explicit command:

```powershell
forge finalize <session-id>
```

이후 `forge run` 종료 시 자동 통합한다.

수집:

- changed files
- command results
- bundle provenance
- completion output
- verification
- Skill evaluation
- learning extraction
- project provenance pointer

핵심 원칙:

> 작업자가 리포트를 쓰는 것이 아니라, Forge가 이미 알고 있는 실행 사실을 최대한 자동으로 채우고 LLM은 해석이 필요한 부분만 보완한다.

---

# 30. `forge learn`

```powershell
forge learn latest
forge learn <task-id>
```

기능:

- artifact schema validation
- DB ingestion
- project-local learning 생성
- global candidate 생성
- duplicate detection
- confidence update
- human-required 항목 보존

---

# 31. `forge report`

```powershell
forge report latest
forge report oracross
forge report <task-id>
```

report는 raw evidence와 해석을 사람이 검토하는 interface다.

---

# 32. `forge cases`

```powershell
forge cases "landing redesign"
```

과거 case와 procedural pattern을 검색한다.

추후 planner가 자동 호출한다.

---

# 33. README에 반드시 남길 개발 철학

README가 command reference만 되어서는 안 된다.

## Why Forge Exists

README 문안 후보:

> AI agents are increasingly capable at writing code, but they still lack a durable system for selecting procedural expertise, proving which guidance was used, preserving execution evidence, and learning which workflows work across projects.
>
> Forge is built to fill that gap. It treats Skills as versioned procedural knowledge, composes them for a task, hands them to agents with project context, verifies the result, and records what was learned for the next task.

## Core Thesis

> **Forge retrieves how to act, not only what to know.**

> **LLMs make semantic judgments. Forge enforces provenance, trust, versions, evidence, and policy.**

## Skill Supply-Chain Principle

> External Skills are untrusted supply-chain inputs. Popularity, authorship, or installation count is not sufficient proof of safety or suitability.

## Learning Principle

> Forge separates observed evidence, inferred conclusions, and human-required outcomes. Agent self-evaluation is never treated as production evidence.

## Adaptive Composition

> Forge reuses proven Skill combinations without becoming locked into them. Low-risk tasks may reserve a small exploration budget for new Skills, while high-risk work defaults to validated capabilities.

## Dogfooding

> Forge should be capable of using Forge to improve Forge, while protected policy and trust boundaries remain human-controlled.

---

# 34. README 권장 구조

```text
# Forge

## What Forge Is
## Why Forge Exists
## Core Thesis
## Current Capabilities
## Quick Start
## High-level Workflow
## Skill Trust Model
## Planner and Composition
## Verification and Learning
## Adaptive Skill Exploration
## Local Memory vs Curated Knowledge
## Recursive Dogfooding
## CLI
## Architecture
## Security
## Development Status
## Roadmap
```

README에는 철학과 사용 흐름을 요약하고 세부 설계는 `docs/`로 보낸다.

---

# 35. 문서 구조

권장:

```text
docs/
├─ PHILOSOPHY.md
├─ ARCHITECTURE.md
├─ PLANNER.md
├─ LEARNING.md
├─ TRUST_AND_SECURITY.md
├─ DOGFOODING.md
└─ adr/
```

## PHILOSOPHY.md 필수 주제

1. Procedural knowledge
2. LLM judgment vs deterministic enforcement
3. Evidence before memory
4. Exploration vs exploitation
5. Agent independence
6. Local-first raw memory
7. Curated global knowledge
8. Recursive but policy-protected improvement
9. Human validation for outcome claims

## ARCHITECTURE.md

- registry
- retrieval
- planner
- composer
- bundle
- agent adapter
- verification
- finalizer
- learning ingestor
- curator
- publisher

## PLANNER.md

- task decomposition
- retrieval
- rerank
- selection/exclusion rationale
- confidence
- conditional skills
- exploration budget
- risk profile

## LEARNING.md

- report schema
- evidence model
- project/global memory
- skill evaluation
- cases
- human feedback
- learning promotion

## TRUST_AND_SECURITY.md

- external Skill threat model
- trust lifecycle
- script execution policy
- credential policy
- recursive safety
- publishing sanitization

## DOGFOODING.md

- ORACROSS case
- Forge-on-Forge procedure
- experiment protocol
- benchmark rules

---

# 36. ADR 후보

1. **ADR: External Skills Are Untrusted**
   - 외부 Skill은 supply-chain input으로 취급한다.
   - popularity는 trust가 아니다.

2. **ADR: Project Repos Do Not Store External Skill Originals**
   - project는 lock/context만 저장한다.
   - Skill original은 global vault/session snapshot에 둔다.

3. **ADR: LLM Planner Cannot Override the Policy Gate**
   - semantic recommendation과 deterministic permission 분리.

4. **ADR: Observed / Inferred / Human-required Evidence Model**
   - learning corruption 방지.

5. **ADR: Raw Memory vs Curated Git Knowledge**
   - privacy와 reproducibility의 경계.

6. **ADR: Exploration Budget**
   - 검증된 Skill만 반복하는 고착화 방지.

7. **ADR: Recursive Forge Policy Boundary**
   - self-improvement가 core trust를 약화시키지 못하게 한다.

8. **ADR: Automatic Finalization**
   - Forge 사용은 자동으로 evidence/report를 남겨야 한다.

9. **ADR: Auto PR before Auto Push**
   - curated knowledge publication의 기본 안전장치.

---

# 37. 개발 로드맵

## Milestone V2.1 — Planner Foundation

구현:

- LLM provider abstraction
- `forge plan`
- task decomposition
- top-K registry retrieval
- LLM rerank
- role assignment
- selection/exclusion reason
- deterministic audit gate
- plan artifact

완료 기준:

> ORACROSS-type goal 하나만 입력해도 현재 사람이 수동으로 만든 것과 유사한 수준의 합리적 Skill team을 제안한다.

---

## Milestone V2.2 — Adaptive Composition

구현:

- historical Skill evidence 조회
- conditional Skill rule
- exploration slot
- risk-aware exploration budget
- composition DAG metadata
- selected/excluded rationale

완료 기준:

> ORACROSS 유사 task에서 `composition-patterns`를 자동 conditional 처리하고, 안전한 새 후보 Skill을 1개 정도 탐색할 수 있다.

---

## Milestone V2.3 — Brief + Agent Handoff

구현:

- execution brief compiler
- expected evidence schema
- Codex adapter
- generic adapter
- bundle + brief one-command path

완료 기준:

> 사용자가 긴 Codex 지시문을 직접 만들 필요가 없다.

---

## Milestone V2.4 — Finalize / Report

구현:

- ORACROSS artifact schema 정식화
- `forge finalize`
- `report.md`
- machine-readable JSON
- provenance
- terminal-state verification filter

완료 기준:

> 사후 report 생성을 agent에게 별도로 요청하지 않는다.

---

## Milestone V2.5 — Learning Ingestion

구현:

- project memory
- global learning candidate
- Skill usage statistics
- case indexing
- evidence classification
- human feedback hook

완료 기준:

> 다음 `forge plan`이 ORACROSS에서 나온 Skill contribution을 실제 selection에 반영한다.

---

## Milestone V2.6 — Curator / GitHub Knowledge PR

구현:

- sanitizer
- secret scan
- project-specific stripping
- generalization
- duplicate detection
- knowledge file generation
- Git branch / PR automation

완료 기준:

> verified task 종료 후 review 가능한 Forge knowledge PR을 자동으로 생성할 수 있다.

---

## Milestone V2.7 — Recursive Dogfooding

Forge가 Forge Vol.2 기능 개발에 자기 planner / report / learn을 사용한다.

완료 기준:

```text
Forge
→ plans Forge change
→ selects Skills
→ agent changes Forge
→ Forge verifies change
→ Forge reports its own usage
→ Forge learns from the task
```

---

# 38. Forge의 우위를 증명하는 방법

가장 큰 리스크는 이것이다.

> **“복잡한 Skill 관리 시스템인데 좋은 prompt 하나보다 별로 낫지 않다.”**

반드시 baseline 비교를 한다.

### A

```text
Agent + ordinary prompt
```

### B

```text
Agent + Forge planner/composition/brief
```

비교:

- task completion
- test pass
- regression
- human rework
- retry count
- implementation quality
- Skill relevance
- time / token cost
- human preference
- production metric when available

Forge의 가치는 “구조가 멋지다”가 아니라:

> **같은 agent를 사용해도 결과가 반복적으로 더 좋아지거나 운영비가 낮아진다.**

로 증명해야 한다.

---

# 39. Anti-goals

Forge Vol.2가 하지 말아야 할 것:

- 모든 것을 거대한 agent framework로 만들지 않는다.
- 전체 Skill catalog를 LLM context에 넣지 않는다.
- Skill이 많을수록 좋다고 생각하지 않는다.
- agent self-report를 성공 metric으로 사용하지 않는다.
- 한 task의 learning을 global truth로 승격하지 않는다.
- raw report를 GitHub main에 자동 push하지 않는다.
- Forge가 자기 core policy를 자동 완화하게 하지 않는다.
- Forge 자체를 관리하기 위한 복잡성이 사용자 이득보다 커지지 않게 한다.

---

# 40. 주요 리스크

## Risk A — Overengineering

좋은 prompt보다 Forge가 느리고 결과 차이가 없으면 실패다.

대응:

- minimal planner MVP
- baseline benchmark
- 기능별 실제 manual pain 확인

## Risk B — Popularity Bias

install count 높은 Skill만 계속 선택될 수 있다.

대응:

- relevance
- evidence
- provenance
- audit
- historical task fit
- exploration

을 분리한다.

## Risk C — Feedback Loop Corruption

agent가 자기 결과를 높게 평가하고 다음번에도 같은 Skill이 선택되는 문제.

대응:

- Observed 우선
- human feedback
- production outcome
- revert signal
- repeated case evidence

## Risk D — Knowledge Contamination

한 프로젝트의 특수한 노하우가 global rule로 승격되는 문제.

대응:

```text
project-local
→ global candidate
→ multi-case support
→ curated knowledge
```

## Risk E — Exploration Risk

새 Skill이 품질을 떨어뜨릴 수 있다.

대응:

- task risk-based exploration budget
- audit
- rollback
- exploration flag
- high-risk task는 기본 zero exploration

---

# 41. North-star Experience

최종 사용자는 다음 정도만 하면 된다.

```powershell
forge run "이 제품의 랜딩을 개선해줘"
```

Forge 내부:

```text
Project 이해
↓
과거 경험 검색
↓
task decomposition
↓
Skill retrieval
↓
검증된 Skill 선택
+
새 Skill 소량 탐색
↓
audit / policy
↓
composition
↓
execution brief
↓
agent
↓
verification
↓
report
↓
learning
↓
curation
↓
knowledge PR
```

사용자는 plumbing을 몰라도 된다.

하지만 필요하면 다음을 모두 drill-down할 수 있어야 한다.

- 왜 이 Skill을 골랐는가
- 왜 다른 Skill을 제외했는가
- 어떤 hash를 사용했는가
- 어떤 evidence가 있었는가
- 무엇을 배웠는가
- 어떤 learning이 아직 hypothesis인가

---

# 42. ORACROSS에서 나온 Vol.2의 기원

이번 dogfooding에서 가장 중요한 것은 UI redesign 자체가 아니다.

실제 Forge 사용 중 다음 질문들이 순서대로 나왔다.

> “왜 search / inspect / audit / pin / compose를 사람이 계속 하지?”

→ **Planner**

> “작업 후 어떤 Skill이 실제로 도움됐는지 남겨야 하지 않나?”

→ **Finalizer / Learning**

> “검증된 Skill만 쓰지 말고 새로운 Skill도 조금씩 시험해야 하지 않나?”

→ **Adaptive Composition / Exploration Budget**

> “정제된 결과를 날짜와 프로젝트 기준으로 Forge GitHub에도 남기면?”

→ **Curator / Knowledge Publisher**

즉 Vol.2는 추상적인 설계가 아니라 **실제 dogfooding friction에서 나온 architecture**다.

이 사실은 Forge development history에 반드시 남긴다.

---

# 43. Immediately Next Work Order

권장 구현 순서:

```text
1. ORACROSS artifact set을 Forge test fixture/spec으로 가져오기
2. Planner provider interface
3. forge plan MVP
4. task decomposition
5. registry top-K retrieval
6. LLM rerank + role assignment
7. policy/audit gate
8. historical evidence lookup
9. adaptive composition + exploration flag
10. execution brief compiler
11. finalize/report
12. learning ingestion
13. cases / skill-usage query
14. curator
15. GitHub knowledge PR
16. Forge-on-Forge dogfooding
```

이 순서의 이유:

- Planner가 앞쪽 두뇌다.
- Finalizer/Learning이 뒤쪽 기억장치다.
- 둘이 연결되어야 Forge가 사용할수록 실제로 개선된다.
- GitHub publish는 충분한 evidence model과 sanitizer가 생긴 뒤 붙인다.

---

# 44. Definition of Done for Vol.2 Core Loop

다음 시나리오가 plumbing command를 거의 사용하지 않고 동작하면 core loop가 완성된 것으로 본다.

```text
사용자:
forge run "public landing conversion redesign"
```

Forge가 자동으로:

- project scan
- past cases lookup
- task decomposition
- Skill recommendation
- new Skill exploration candidate
- audit
- composition
- brief
- agent handoff
- verification
- report
- learning
- project memory
- curated knowledge candidate

를 수행한다.

그리고 다음 유사 task에서:

- 과거 High contribution Skill 재사용
- Low contribution Skill conditional 처리
- exploration candidate 교체
- previous evidence 설명

까지 가능해야 한다.

---

# 45. README 최종 철학 문구 후보

> **Forge retrieves how to act, not only what to know.**

> **LLMs judge meaning. Forge enforces evidence, provenance, trust, and versioned execution context.**

> **Every Forge-assisted task should leave the system with more verified procedural knowledge than it had before.**

한국어:

> Forge의 목적은 더 많은 Skill을 모으는 것이 아니다. 프로젝트의 목표를 이해하고, 필요한 절차를 선택하고, 검증된 전문성을 조합하고, 실행 결과를 증거와 함께 기록하여 다음 판단을 더 나아지게 만드는 것이다.

> Forge를 사용할수록 단순한 로그가 아니라 **검증된 실행 경험**이 쌓여야 한다.

---

# 46. Final Principle

Forge의 폐루프:

```text
UNDERSTAND
→ PLAN
→ RETRIEVE
→ JUDGE
→ VERIFY
→ COMPOSE
→ EXECUTE
→ VERIFY
→ REPORT
→ LEARN
→ CURATE
→ PUBLISH
→ IMPROVE
```

이 루프는 일반 프로젝트에도 적용되고 Forge 자기 자신에게도 적용된다.

하지만 경계는 유지한다.

> **Forge는 스스로 더 똑똑해질 수 있어야 하지만, 스스로 증거의 기준과 신뢰의 기준을 낮출 수는 없어야 한다.**

이것이 Forge Vol.2의 핵심 개발 철학이다.

---

# Appendix A. ORACROSS Dogfooding Provenance

```text
Project:
ORACROSS

Task:
2026-08-12-growth-visual-redesign

Forge session:
session-8b7b45eed05e4874a954c9d823ff149d

Global report:
~/.forge/history/oracross/2026-08-12-growth-visual-redesign/report.md

Artifacts:
task.json
composition.json
skill-evaluations.json
applied-patterns.json
verification.json
learnings.json
```

대표 learning:

```text
product-marketing-context
→ high contribution

page-cro
→ high contribution

frontend-design
→ high contribution

composition-patterns
→ low direct contribution
→ conditional future selection
```

---

# Appendix B. Suggested Knowledge Case Template

```markdown
---
date:
project:
task:
task_type:
skills:
evidence:
status:
---

# Case

## Context
## Goal
## Constraints
## Composition
## Exploration Candidate
## Applied Patterns
## Observed Evidence
## Inferred Learnings
## Human-required Validation
## Skill Contribution
## What To Reuse
## What Not To Reuse
## Future Experiment
```

---

# Appendix C. Suggested Planner Output Schema

```json
{
  "goal": "",
  "taskType": [],
  "risk": "low|medium|high",
  "roles": [],
  "selectedSkills": [
    {
      "id": "",
      "role": "",
      "reason": "",
      "confidence": 0.0,
      "exploration": false,
      "historicalEvidence": []
    }
  ],
  "excludedSkills": [],
  "dependencies": [],
  "verificationPlan": [],
  "humanApprovalRequired": []
}
```

---

# Appendix D. Suggested Finalization State Machine

```text
planned
↓
bundled
↓
running
↓
implementation_complete
↓
verification_pending
↓
verified
↓
finalizing
↓
reported
↓
learning_ingested
↓
curation_pending
↓
curated
↓
published
```

Failure states:

```text
verification_failed
partial
aborted
human_review_required
```

이 상태를 명시하면 “agent가 완료했다고 말함”과 “실제로 검증이 완료됨”을 구분할 수 있다.

---

# Appendix E. Forge가 계속 물어야 할 질문

> **이 기능이 정말 agent의 성능을 높이거나 사용자의 운영비를 줄이는가?**

> **아니면 Forge 자체를 관리하기 위한 또 다른 복잡성만 추가하는가?**

후자라면 기능을 줄인다.

Forge의 목표는 복잡한 orchestration system을 만드는 것이 아니다.

> **더 좋은 절차를 더 적은 수동 조작으로 재사용하고, 그 결과를 검증 가능한 경험으로 축적하는 것.**

그것이 Forge의 기준이다.
