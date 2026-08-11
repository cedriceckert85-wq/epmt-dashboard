import argparse, json, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/"state/project_state.json"

class StateError(Exception): pass

def load_state():
    try:
        raw=STATE.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise StateError("canonical state file missing") from e
    try:
        st=json.loads(raw)
    except json.JSONDecodeError as e:
        raise StateError(f"canonical state JSON invalid: {e}") from e
    if not isinstance(st,dict) or "phase_id" not in st or "lifecycle" not in st:
        raise StateError("canonical state schema incomplete")
    return st

def main():
    p=argparse.ArgumentParser()
    p.add_argument("command", choices=["doctor","status","run-phase00","run","approve"])
    p.add_argument("--phase")
    p.add_argument("--commit")
    p.add_argument("--approver")
    p.add_argument("--decision", choices=["APPROVE","REJECT"])
    p.add_argument("--dry-run", action="store_true")
    args=p.parse_args()

    try:
        st=load_state()
    except StateError as e:
        print(f"BLOCKED: {e}",file=sys.stderr)
        return 3

    if args.command=="status":
        print(json.dumps(st,indent=2))
        return 0

    if args.command=="doctor":
        print("doctor: Phase 00 capability checks must be implemented and pass before general run is enabled.")
        return 0

    if args.command=="run-phase00":
        if st.get("phase_id")!="00":
            print("BLOCKED: run-phase00 only valid while canonical phase is 00",file=sys.stderr)
            return 3
        print("Phase 00 bootstrap path enabled. Live LoL phases remain disabled.")
        return 0

    if args.command=="run":
        if st.get("phase_id")=="00" and st.get("last_gate")!="PASS":
            print("BLOCKED: Phase 00 not passed. Use run-phase00 for bootstrap work.",file=sys.stderr)
            return 3
        print("General run placeholder: Phase 00 implementation must replace skeleton.")
        return 0 if args.dry_run else 3

    if args.command=="approve":
        if not (args.commit and args.approver and args.decision):
            print("BLOCKED: approve requires --commit --approver --decision",file=sys.stderr)
            return 2
        print(json.dumps({"commit_sha":args.commit,"approver":args.approver,"decision":args.decision}))
        print("UNIMPLEMENTED: approval record persistence belongs to Phase 00.",file=sys.stderr)
        return 4

    return 1

if __name__=="__main__":
    raise SystemExit(main())
