"""One-time seed/merge of laptop-era history into the cloud volume.

Runs on every container boot (idempotent):
  - track_record.jsonl: merge by date — volume entries win over seed entries.
  - live_log.jsonl: copy only if the volume has none.
"""
import json
from pathlib import Path

SEED = Path("seed_data")
DATA = Path("data")


def merge_track_record() -> None:
    seed_f = SEED / "track_record.jsonl"
    vol_f = DATA / "track_record.jsonl"
    if not seed_f.exists():
        return
    records: dict[str, str] = {}
    for f in (seed_f, vol_f):  # volume read second → wins on date conflicts
        if f.exists():
            for line in f.read_text().splitlines():
                if line.strip():
                    try:
                        records[json.loads(line)["date"]] = line
                    except (json.JSONDecodeError, KeyError):
                        continue
    vol_f.write_text("\n".join(records[d] for d in sorted(records)) + "\n")
    print(f"[seed] track_record merged: {sorted(records)}")


def copy_live_log() -> None:
    seed_f = SEED / "live_log.jsonl"
    vol_f = DATA / "live_log.jsonl"
    if seed_f.exists() and (not vol_f.exists() or vol_f.stat().st_size == 0):
        vol_f.write_text(seed_f.read_text())
        print("[seed] live_log copied")


if __name__ == "__main__":
    DATA.mkdir(exist_ok=True)
    merge_track_record()
    copy_live_log()
