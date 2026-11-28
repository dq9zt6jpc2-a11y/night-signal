"""Allow same-day supplements only when they resolve pending work without losing articles."""
import json
import sys
from pathlib import Path


def advances(previous, incoming):
    def pending(issue):
        return {(row["request_id"], row["event_id"]) for row in issue.get("pending_editorial_events", [])}

    def articles(issue):
        return {json.dumps(card, ensure_ascii=False, sort_keys=True) for card in issue["cards"]}

    return (previous["issue_date"] == incoming["issue_date"]
            and previous["coverage_manifest"]["evidence_sha256"] == incoming["coverage_manifest"]["evidence_sha256"]
            and pending(incoming) < pending(previous)
            and articles(previous) <= articles(incoming))


if __name__ == "__main__":
    old, new = (json.loads(Path(arg).read_text()) for arg in sys.argv[1:])
    sys.exit(0 if advances(old, new) else 1)
