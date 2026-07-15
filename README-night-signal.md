# NIGHT SIGNAL

NIGHT SIGNAL is a daily public issue that collects broadly and publishes
evidence-backed important updates in the established format.

## Production command

```bash
GITHUB_TOKEN=... python3 scripts/night_signal_publish.py YYYY-MM-DD
```

Recovery may explicitly reuse a fresh same-date Evidence:

```bash
GITHUB_TOKEN=... python3 scripts/night_signal_publish.py YYYY-MM-DD --reuse-evidence
```

Deploy committed state without collecting:

```bash
python3 scripts/night_signal_publish.py YYYY-MM-DD --deploy-existing
```

Verify public root and dated pages:

```bash
python3 scripts/night_signal_publish.py YYYY-MM-DD --public-audit
```

## Production path

1. `night_signal_publish.py` owns the run.
2. `night_signal_collect.py` performs broad source discovery.
3. `night_signal_evidence.py` writes the single verified Evidence bundle.
4. `night_signal_editor.py` builds all important-update state.
5. `night_signal_state.py` validates and renders the issue.
6. Local audits pass before commit.
7. `pages.yml` deploys committed state and the owner verifies public URLs.

The repository retains the current published issue plus its three most recent
predecessors: their Evidence/Issue state, sample HTML, linked detail pages, and
dated pages. The Editor uses those prior issues for novelty comparison, and the
public archive lets readers catch up. Older issues are deleted only after the new
issue passes every local gate.

The timing policy derives the fresh-collection window from the 19:00 deadline,
the 105-minute end-to-end runtime budget, and a 30-minute safety margin. Scheduled
heartbeats may arrive early or late; only the first actual start from 16:45 through
18:59 runs collection. Earlier starts exit without model calls, later starts fail
without spending collection or model tokens, and later heartbeats exit after a
verified publication. Scheduled publication always collects fresh Evidence.

## Configuration

- `config/night_signal_coverage.json`: categories, topics, and coverage rules.
- `config/night_signal_sources.json`: seed sources.
- `config/night_signal_models.json`: bounded model route and effort settings.
- `config/night_signal_operations.json`: deadline, runtime, safety, and scheduler policy.

## Verification

```bash
python3 scripts/night_signal_state.py --self-test
python3 scripts/night_signal_publish.py --self-test
python3 scripts/night_signal_collect.py --self-test
python3 scripts/night_signal_editor.py --self-test
python3 scripts/night_signal_model_audit.py --self-test
python3 scripts/publication_timing.py --self-test
python3 scripts/publication_schedule_audit.py
python3 scripts/simulate_runtime_failures.py
python3 scripts/simulate_quality_gate_failures.py
```

The complete design contract is in `docs/night-signal-basic-design.md`.
