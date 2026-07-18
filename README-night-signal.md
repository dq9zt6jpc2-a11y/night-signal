# NIGHT SIGNAL

NIGHT SIGNAL is a daily public issue that collects broadly and publishes
evidence-backed important updates in the established format.

## Production commands

GitHub Actions first creates the zero-model review artifact. The ChatGPT Plus
Codex owner then restores it and prepares the compact packet:

```bash
python3 scripts/night_signal_review_artifact.py YYYY-MM-DD
python3 scripts/night_signal_plus_editor.py YYYY-MM-DD --prepare
python3 scripts/night_signal_plus_editor.py YYYY-MM-DD \
  --apply-review state/YYYY-MM-DD/editor_review.json
```

Render and deploy validated state without collecting or reviewing again:

```bash
python3 scripts/night_signal_publish.py YYYY-MM-DD \
  --deploy-existing --deploy-edited-final-evidence --verification-profile deploy
```

公開済みの同一号について、コードや静的ナビゲーションだけを再配信する場合は
`--deploy-existing --redeploy-published` を使う。この経路は公開中の号とローカル号の
内容一致を先に監査し、再収集やAI編集を行わない。初回公開には使用しない。

Verify public root and dated pages:

```bash
python3 scripts/night_signal_publish.py YYYY-MM-DD --public-audit
```

## Production path

1. `unattended-collection.yml` and `night_signal_collect.py` collect broad Web Evidence.
2. `night_signal_evidence.py` writes the single verified Evidence bundle.
3. `night_signal_plus_editor.py --prepare` removes only exact/semantic duplicates and
   unchanged three-issue history, without a candidate cap.
4. The ChatGPT Plus Codex owner reviews every remaining event once with GPT-5.6 Terra.
5. `night_signal_plus_editor.py --apply-review` verifies every event and fact source.
6. `night_signal_state.py` validates and renders the issue.
7. Local audits pass before commit; `pages.yml` deploys committed state and the owner
   verifies root and dated public URLs.

The repository retains the current published issue plus its three most recent
predecessors: their Evidence/Issue state, sample HTML, linked detail pages, and
dated pages. The Editor uses those prior issues for novelty comparison, and the
public archive lets readers catch up. Older issues are deleted only after the new
issue passes every local gate.

Evidence heartbeats before 16:45 JST exit without collection. The 16:47 and 17:17
heartbeats create or reuse final Evidence artifacts but never invoke AI or publish.
The GitHub-plugin-enabled ChatGPT Work-mode primary owner runs at 17:50 and the
recovery owner at 18:25. The owner first proves GitHub write access, then performs
only the missing review or correction. Recovery reuses the last completed stage:
Evidence, accepted request/event responses, Issue, commit, or Pages deployment.

## Configuration

- `config/night_signal_coverage.json`: categories, topics, and coverage rules.
- `config/night_signal_sources.json`: seed sources.
- `config/night_signal_ai.json`: zero-additional-charge policy and Plus model route.
- `config/night_signal_operations.json`: deadline, runtime, safety, and scheduler policy.

## Verification

```bash
python3 scripts/night_signal_state.py --self-test
python3 scripts/night_signal_publish.py --self-test
python3 scripts/night_signal_collect.py --self-test
python3 scripts/night_signal_editor.py --self-test
python3 scripts/night_signal_plus_editor.py --self-test
python3 scripts/night_signal_review_artifact.py --self-test
python3 scripts/quality_gate.py --self-test
python3 scripts/publication_timing.py --self-test
python3 scripts/publication_schedule_audit.py
python3 scripts/simulate_runtime_failures.py
python3 scripts/simulate_consecutive_days.py
python3 scripts/simulate_quality_gate_failures.py
```

Official OpenAI model availability is checked on Mondays only. A new Codex-capable
candidate is evaluated on representative Evidence for coverage, fact accuracy,
summary quality, runtime, and total tokens. It never changes production automatically.

The complete design contract is in `docs/night-signal-basic-design.md`.
