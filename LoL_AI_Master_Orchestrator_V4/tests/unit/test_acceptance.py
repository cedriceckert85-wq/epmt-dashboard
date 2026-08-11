from orchestrator import acceptance


def rec(**kw):
    base = {"phase_id": "04", "finding_id": "F1", "commit_sha": "abc",
            "decision": "ACCEPT", "reason": "r", "approver": "h", "timestamp_utc": "t"}
    base.update(kw)
    return base


def test_valid_accept():
    ids, reasons = acceptance.accepted_ids([rec()], phase_id="04", candidate_commit="abc")
    assert ids == {"F1"} and reasons == []


def test_sha_scoping_accepts_nothing_without_error():
    # stale acceptance must accept nothing, but must NOT raise a blocking
    # error (that would permanently block a clean rebuild).
    ids, reasons = acceptance.accepted_ids([rec(commit_sha="old")], phase_id="04",
                                           candidate_commit="abc")
    assert ids == set() and reasons == []


def test_other_phase_ignored_silently():
    ids, reasons = acceptance.accepted_ids([rec(phase_id="05")], phase_id="04",
                                           candidate_commit="abc")
    assert ids == set() and reasons == []


def test_load_error_surfaces():
    ids, reasons = acceptance.accepted_ids([{"__load_error__": "x.json: boom"}],
                                           phase_id="04", candidate_commit="abc")
    assert ids == set() and any("unreadable" in r for r in reasons)
