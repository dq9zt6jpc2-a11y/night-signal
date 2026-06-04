# NIGHT SIGNAL Basic Design

## 0. 設計判断サマリ

今回の見直しで一番大事な判断は、NIGHT SIGNALを「HTMLを作る
スクリプト群」ではなく、「毎日の情報状態を進める状態機械」として
扱うことです。

品質を落とさずに処理負荷を下げるには、ゲートを増やすのではなく、
不具合が発生する前の状態で止める必要があります。つまり、公開後に
「古い」「少ない」「題目が変」「要約が怪しい」と検査するのではなく、
次の状態がそろわない限り、後続工程へ進ませません。

採用する基本構造:

```text
探索範囲を決める
  -> 情報源を観測する
  -> 候補ニュースに正規化する
  -> 採用/不採用を判断する
  -> 決定済みデータからHTMLを描画する
  -> 当日号だけを公開する
```

この設計では、AIは「文章をそれっぽく書く担当」ではありません。AIは
OpenAIのResponses API、Structured Outputs、Function Calling、Agents
SDK/Tracingを使い、観測、候補、採用判断をスキーマに従って返す担当です。
公開HTMLは決定済みJSONから決定論的に生成します。

これにより、足し算型の対策ではなく、次の三つを同時に満たします。

- 網羅性: `category x watch topic x source role x channel` の観測slotで証明する。
- 正確性: 事実、反証、日付、出典、採用理由を構造化してから文章化する。
- 効率性: 重要度、更新頻度、再利用ポリシー、モデル経路で処理量を制御する。

## 0.1 採用しない設計

次の設計は、短期的には直ったように見えても再発するため採用しません。

- ゲートを増やして流出だけ止める設計。
- 日付別の再生成スクリプトを毎日足す設計。
- 「カテゴリごとに何件出す」という件数合わせ設計。
- Deep Researchや大型モデルに丸投げして、最終HTMLを直接書かせる設計。
- 公式Webだけ、またはニュース検索だけで網羅性を主張する設計。
- 予定、カレンダー、開催前情報をニュース価値として扱う設計。

## 0.2 最適設計と判断した理由

最新AIを使うべき場所は、量の多い全工程ではなく、判断の不確実性が
高い部分です。毎晩すべてを大型モデルで読ませると、費用とトークンが
増え続け、結局また運用不能になります。

そのため、通常の抽出は小さく安い構造化モデルとキャッシュで処理し、
重要・曖昧・影響が大きい候補だけを frontier reasoning model に回します。
広い探索範囲そのものは、毎晩ゼロから考えるのではなく、定期的な
frontier reviewで更新します。

この構造なら、SpaceX、F1、OpenAI、SoftBank、YOASOBI/幾田りら、
日本経済、北米経済、SNS/X、YouTubeのように情報網が増えても、
単純な足し算ではなく「観測slot」と「再利用可能性」で増加を吸収できます。

## 1. Purpose

NIGHT SIGNAL is not a static page generator. It is a daily intelligence system
that must reliably do four things:

1. Publish the current JST issue only when the issue is actually ready.
2. Collect broadly enough that important changes are unlikely to be missed.
3. Select and summarize only items that change the reader's understanding.
4. Keep operating cost and token use bounded as coverage expands.

The design must prevent failures from arising, not merely detect them after
HTML has already been generated.

## 2. Current Design Rejection

The current implementation pattern is not acceptable as the long-term design.

- Date-specific rebuild scripts create daily hand-built programs.
- Publication is triggered by repository changes, not by a verified current
  issue state.
- Coverage is represented after generation, so missing collection can be
  hidden until a late gate.
- Quality gates have accumulated as separate checks, which increases cognitive
  load and token load without clarifying the core process.
- The system can pass some checks while the real failure is earlier: no current
  issue was generated, no current issue was selected, or collection ownership
  was missing.

This is a means-first structure. The replacement must be state-first.

## 3. Design Principle

The system is a state machine:

```text
Plan Frontier
  -> Collect Observations
  -> Normalize Candidates
  -> Decide Topic Value
  -> Render Issue
  -> Publish
```

Each state has explicit inputs, outputs, invariants, and blockers. A later state
must not compensate for a missing earlier state.

## 4. Non-Negotiable Invariants

- No stale publication: `site/index.html` must not be updated unless the
  selected issue is the current JST issue and required artifacts exist.
- No silent fallback: older issue files must never be used because today's issue
  is missing.
- No free-form collection proof: coverage must be represented as structured
  observations, candidates, and decisions.
- No schedule-only cards: freshness is eligibility, not value.
- No category quota filling: card count is variable and follows actual change.
- No hand-authored daily logic as the primary path: date-specific rebuild
  scripts may exist only as legacy fixtures during migration.
- No model as uncontrolled author: models produce structured records; renderers
  produce public HTML.
- No equal-cost search: high-change/high-impact sources are checked more
  aggressively; low-change sources use reuse and differential checks.

## 5. State Definitions

### 5.1 Plan Frontier

Input:

- `config/night_signal_coverage.json`
- current JST date
- prior issue state
- source reliability and velocity metadata

Output:

- a complete list of observation slots

Each observation slot contains:

- category
- watch topic
- source role
- channel
- priority
- reuse policy
- model route

Baseline source roles:

- primary or official
- independent media or data
- social or video signal when relevant

The frontier is complete only when every configured watch topic has the required
slots. Completeness is not "each category has at least one URL."

### 5.2 Collect Observations

Input:

- frontier slots
- source connectors or fetch tools
- cached observations

Output:

- `SourceObservation` records

Each observation must include:

- URL or stable source identifier
- observed time in JST
- source publication/update date when available
- source role
- channel
- claim atoms
- short evidence summary
- cache/reuse status

The collector does not write public copy.

### 5.3 Normalize Candidates

Input:

- source observations grouped by watch topic

Output:

- `Candidate` records

Each candidate must include:

- title candidate
- source URLs
- source date
- change class
- material facts
- counter-evidence status
- uncertainty notes

Candidates can be rejected later, but weak or duplicate candidates should still
exist as structured records so the system can prove that the area was checked.

### 5.4 Decide Topic Value

Input:

- candidates
- prior issue decisions
- policy and topic-value schema

Output:

- `TopicDecision` records

Each decision must include:

- adopt or reject
- topic value class
- reader delta
- materiality basis
- rejection class and reason when rejected

This is where AI reasoning matters most. It is also where over-publication and
under-publication are controlled.

### 5.5 Render Issue

Input:

- adopted candidates
- topic decisions
- detail-page schema

Output:

- root sample HTML
- dated `site/YYYY-MM-DD/index.html`
- detail pages
- extraction log with manifest

Rendering is deterministic. The renderer should not decide whether something is
important.

### 5.6 Publish

Input:

- selected issue marker
- rendered artifacts
- publication audit

Output:

- updated public site

Publication can occur only if:

- marker equals current JST issue date
- root and dated issue files exist
- extraction log exists
- quality and coverage audits pass
- public URL verifies the same issue date and same card titles

## 6. AI Technology Evaluation

### Responses API

Use as the primary API surface for agentic workflows because it supports tools,
structured output, multimodal input, and stateful interactions. It is the right
base for a collection-to-decision pipeline.

Adopt.

### Structured Outputs

Use for observations, candidates, decisions, and issue state. This prevents
missing fields, invalid enums, and prompt-only formatting discipline.

Adopt.

### Function Calling

Use for source fetching, source search, cache lookup, prior issue lookup, and
publication status lookup. The model should request data through tools rather
than invent source facts.

Adopt.

### Agents SDK And Tracing

Use when splitting collection by domain or source role. Traces matter because
the most important operational question is not "did the final page pass?" but
"which collector, source role, or watch topic failed?"

Adopt for orchestration and observability, not as a substitute for schemas.

### Deep Research Models

Deep research models are attractive for broad horizon scanning, but they are not
the nightly deterministic publication engine by themselves. They may summarize
the world well, but their output still must be normalized into the same
observation/candidate/decision schema.

Adopt for periodic frontier review, not direct daily rendering.

### Large Frontier Models

Use GPT-5.5-class frontier reasoning for:

- frontier planning
- ambiguous/high-impact topic arbitration
- periodic policy review
- postmortem reasoning

Do not use frontier models for every source extraction.

Selective adopt.

### Smaller Structured Models

Use cheaper structured-output-capable models for:

- extracting claim atoms
- normalizing observations
- deduplicating routine candidates
- turning source snippets into candidate records

Adopt.

### Batch, Caching, And Reuse

Use caching and differential checks for low-change sources. Use batch/flex style
processing for non-urgent horizon scans or bulk normalization. This is part of
the design, not an optional cost tweak.

Adopt.

## 7. Model Routing

The model choice follows the state, not the user's anxiety level.

| State | Default Model Class | Reason |
| --- | --- | --- |
| Plan Frontier | frontier reasoning | Requires coverage strategy and gap reasoning |
| Collect Observations | tool calls plus cheap extraction | High volume, low creativity |
| Normalize Candidates | cheap structured model | Schema-heavy transformation |
| Decide Topic Value | mixed; frontier for ambiguous/high-impact | Judgment matters |
| Render Issue | no model | Deterministic output |
| Publish | no model | Deterministic audit |
| Weekly Frontier Review | deep research or frontier | Broad horizon update |

## 8. Efficiency Design

Efficiency is a first-class requirement because brute-force coverage will make
the app unusable.

Each observation slot gets:

- priority: high / normal / low
- reuse policy: daily fetch / reuse unless primary changed / scheduled refresh
- model route: cheap extractor / frontier arbitration / no model

High-priority examples:

- OpenAI release and official X
- SpaceX launch status and official X/YouTube
- F1 race result or official team announcement
- market-price/NAV movements
- central bank/statistical releases

Reusable examples:

- static policy pages
- stable YouTube channels without new uploads
- official pages whose last-modified/hash is unchanged
- background explainers and previously verified source maps

Efficiency metrics:

- observation slots required
- slots satisfied by cache
- slots fetched live
- model calls by route
- frontier-model calls
- unresolved blockers
- adopted cards per live-fetch cost

## 9. Coverage Design

Coverage is not a list of categories. Coverage is a matrix:

```text
category x watch topic x source role x channel
```

A public issue is allowed only after every required matrix cell is either:

- observed live,
- reused with a valid reuse policy,
- marked source unavailable with reason,
- marked not applicable by contract.

The system must record empty results. "Nothing important happened" is valid only
when the required cells were checked.

## 10. Extraction Design

Extraction must avoid two failures:

- under-selection: missing important topics
- over-selection: publishing routine or schedule-only items

The candidate pipeline handles this with:

- claim atoms
- source roles
- source dates
- material facts
- counter evidence
- topic value decisions
- rejection classes

The title and summary are produced after adoption. This avoids the failure mode
where a weak item gets a polished title and then looks important.

## 11. Publication Design

Publication is downstream of state readiness.

Pages workflow should publish only when issue artifacts or the issue marker
change. Code/docs/config-only changes must not republish a stale selected issue.

Daily automation must have a generation owner. If the current issue does not
exist by a warning time, the failure should be "generation owner missing" or
"collection incomplete", not "public page stale" hours later.

## 12. Existing Feature Equivalence

The new design must preserve:

- daily public root page
- dated issue URL
- detail pages
- extraction log
- coverage manifest
- source class evidence
- no-change checks
- latest three calendar day labels
- topic-value fields
- claim verification
- publication audit
- public URL verification

Any implementation that drops one of these is not equivalent.

## 13. Better-Than-Current Criteria

The redesign is better only if it can prove all of the following:

- It fails before publication when the current issue does not exist.
- It shows exactly which watch topic/source slot is missing.
- It avoids rerunning expensive collection for unchanged low-change sources.
- It prevents a schedule-only item from becoming a public card.
- It prevents stale issue artifacts from being republished by code-only changes.
- It produces the same or better public artifacts from structured records.
- It reduces daily human/agent decision surface, not increases it.

## 14. Implementation Phases

### Phase 0: Design Freeze

Finalize schemas, state transitions, invariants, and metrics. No publication
behavior changes yet.

### Phase 1: Read-Only State Inspection

Build frontier and readiness reports without changing issue generation. This
proves the current failure modes.

### Phase 2: Structured Collection Store

Write observations and candidates to dated JSON state files. Keep old renderers.

### Phase 3: Renderer From State

Render issue HTML from adopted candidate records instead of date-specific Python
scripts.

### Phase 4: Agentic Collection

Use Responses API, function calling, structured outputs, and tracing for
collection and decision stages.

### Phase 5: Remove Legacy Daily Scripts

Date-specific rebuild scripts become archived fixtures, not the daily path.

## 15. Decision

The recommended design is:

```text
State-machine core
+ structured observation/candidate/decision schemas
+ deterministic rendering
+ narrow publication trigger
+ model routing
+ cache-aware observation slots
+ traced agent collectors
+ periodic deep-research frontier review
```

This is stronger than a gate-first design and stronger than a single "deep
research then summarize" design. It separates coverage, judgment, rendering,
and publication, while keeping all four connected by explicit state.

## 16. 同等性証明

効率化後も、次の公開品質を落としてはいけません。実装はこの表を
満たした場合だけ同等とみなします。

| 既存で必要だった能力 | 新設計での保持方法 | 証明方法 |
| --- | --- | --- |
| 毎日のroot公開ページ | `Render Issue`がroot sampleと`site/index.html`を生成 | current issue audit |
| 日付別URL | dated issue artifactを必須状態にする | readiness state |
| 詳細ページ | adopted candidateごとにdetail recordを生成 | manifest cross-check |
| extraction log | observation/candidate/decisionをlogに出す | coverage audit |
| Web/SNS/X/YouTube証跡 | observation slotのchannelで保持 | missing slot count |
| no-change checks | 観測結果として「変化なし」を記録 | source observation records |
| 日本語概要 | 採用後だけsummary rendererで生成 | topic decision + render audit |
| 参照URL | candidate source URLsを必須にする | schema validation |
| 最新3日ラベル | render stageの表示仕様として保持 | HTML snapshot/audit |
| 題名の正確性 | titleはcandidate factsから生成し、予定だけで採用しない | topic-value decision |
| 公開前検証 | publish stateで当日markerと公開artifactを確認 | publication audit |

重要なのは、同等性を「ページが見えるか」ではなく「公開ページを
構成する状態が欠けていないか」で証明することです。

## 17. 失敗発生を抑える構造

過去の問題は、最後の品質ゲート不足ではなく、前段の状態欠落が
後段まで流れたことです。新設計では次のように発生源で止めます。

| 過去の失敗 | 発生源 | 新設計の停止位置 |
| --- | --- | --- |
| 今日の号が公開されない | generation owner不在 | `Plan Frontier` / `Render Issue` |
| 昨日の号が残る | markerとartifactの不一致 | `Publish` |
| 題材が少なすぎる | coverage matrix未観測 | `Collect Observations` |
| SpaceXなど重要領域の抜け | watch topic/source role不足 | `Plan Frontier` |
| F1予定を結果のように扱う | freshnessを価値と誤認 | `Decide Topic Value` |
| 題名/要約が事実とずれる | 自由作文で生成 | `Normalize Candidates` / `Render Issue` |
| チェック追加で重くなる | gatesが分散 | state schemaに集約 |

## 18. 実装の進め方

次に進む順序は固定します。

1. Phase 0として、この基本設計をrepo内の正本にする。
2. Phase 1として、現在の生成物を変更せずにread-only state inspectionを完成させる。
3. Phase 2として、観測・候補・判断をdated JSON stateとして保存する。
4. Phase 3として、HTMLをJSON stateから生成する。
5. Phase 4として、Responses API/Structured Outputs/Function Calling/Agents SDKを本番経路に入れる。
6. Phase 5として、日付別rebuild scriptを日次経路から外す。

ここまで進むまで、個別ニュースの手直しやゲート追加は原則として
根本対策扱いにしません。

## 19. OpenAI技術の確認元

2026-06-04時点で、設計判断の根拠として公式ドキュメントを確認済みです。

- Responses API migration: https://developers.openai.com/api/docs/guides/migrate-to-responses
- Structured Outputs: https://developers.openai.com/api/docs/guides/structured-outputs
- Function Calling: https://developers.openai.com/api/docs/guides/function-calling
- Agents SDK: https://developers.openai.com/api/docs/guides/agents
- GPT-5.5 model: https://developers.openai.com/api/docs/models/gpt-5.5/
