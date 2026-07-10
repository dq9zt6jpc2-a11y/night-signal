# NIGHT SIGNAL

NIGHT SIGNAL is a daily public issue that collects broadly and publishes
evidence-backed important updates in the established format.

## Production command

```bash
GITHUB_TOKEN=... python3 scripts/night_signal_publish.py YYYY-MM-DD
```

The 17:15 fallback may reuse a fresh same-date Evidence:

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

Scheduled attempts run at 15:35 and 17:15 JST for publication by 19:00. The second attempt exits when
publication is already verified and reuses a fresh checkpoint after downstream
failure.

## Configuration

- `config/night_signal_coverage.json`: categories, topics, and coverage rules.
- `config/night_signal_sources.json`: seed sources.
- `config/night_signal_models.json`: bounded model route and effort settings.

## Verification

```bash
python3 scripts/night_signal_state.py --self-test
python3 scripts/night_signal_publish.py --self-test
python3 scripts/night_signal_collect.py --self-test
python3 scripts/night_signal_editor.py --self-test
python3 scripts/publication_schedule_audit.py
python3 scripts/simulate_runtime_failures.py
python3 scripts/simulate_quality_gate_failures.py
```

The complete design contract is in `docs/night-signal-basic-design.md`.
