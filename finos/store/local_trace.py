"""Appends one JSON line per stage to runs/trace.jsonl. Stands in for Supabase until Slice 2."""

import json
from datetime import datetime, timezone
from pathlib import Path

TRACE_PATH = Path("runs/trace.jsonl")


class LocalTrace:
    def __init__(self, trace_path: Path = TRACE_PATH):
        self.trace_path = trace_path
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event_id: str, stage: str, payload: dict) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event_id": event_id,
            "stage": stage,
            "payload": payload,
        }
        with self.trace_path.open("a") as f:
            f.write(json.dumps(record, default=str) + "\n")
