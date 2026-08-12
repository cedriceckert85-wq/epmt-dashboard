"""BUILD_PASS vs RELEASE_CERTIFIED.

A green one-shot build is NOT the same as a proven release. This module
computes, from canonical state, whether the run is merely BUILT (all
requested phases merged, real-world tests possibly deferred / gates
auto-approved) or actually RELEASE_CERTIFIED (every real-world test ran on
the target hardware AND every subjective quality gate was approved by a
real human).

The distinction is the fix for the review finding that Phase 20 could
report PASS without the real POC ever running.
"""


def certification_status(st, *, all_phases):
    """Return a dict describing build vs certification for the given state.

    all_phases: iterable of phase config dicts (id, human_review_required, ...).
    """
    history = st.get("phase_history", {})
    phase_by_id = {str(p["id"]).zfill(2): p for p in all_phases}

    built_ids = sorted(pid for pid, h in history.items() if h.get("gate") == "PASS")

    # 1) real-world tests that were deferred (never actually run)
    deferred = st.get("deferred_tests", {})
    deferred_gaps = {pid: sorted(names) for pid, names in deferred.items() if names}

    # 2) subjective quality gates not approved by a real human
    human_gaps = []
    for pid, h in history.items():
        ph = phase_by_id.get(pid, {})
        if ph.get("human_review_required") or h.get("human_review_required"):
            if h.get("human_review") != "human":
                human_gaps.append(pid)
    human_gaps = sorted(human_gaps)

    # certification is a claim about the WHOLE (non-optional) pipeline — a
    # partial `--phases 00` run must never read as RELEASE_CERTIFIED.
    required_ids = sorted(
        str(p["id"]).zfill(2) for p in all_phases
        if not (p.get("optional") and not p.get("enabled_by_default", True)))
    missing_phases = [pid for pid in required_ids if pid not in set(built_ids)]

    certified = not deferred_gaps and not human_gaps and not missing_phases
    return {
        "built_phases": built_ids,
        "certified": certified,
        "deferred_gaps": deferred_gaps,
        "human_review_gaps": human_gaps,
        "missing_phases": missing_phases,
    }


def format_status(status, *, overall):
    lines = []
    if status["certified"] and overall == "done":
        lines.append("Release status: **RELEASE_CERTIFIED** — every real-world test ran and "
                     "every quality gate was human-approved.")
        return "\n".join(lines)
    if overall == "done":
        lines.append("Release status: **BUILD_PASS (not yet RELEASE_CERTIFIED)** — the software "
                     "is built and all mockable tests passed, but real-world evidence is still "
                     "open. To certify, run on the target hardware with `--certify` and give the "
                     "quality gates a real human review.")
    else:
        lines.append("Release status: **INCOMPLETE** — the build did not finish; see above.")
    if status["deferred_gaps"]:
        lines.append("")
        lines.append("Open real-world tests (deferred, never run — NOT counted as passing):")
        for pid in sorted(status["deferred_gaps"]):
            lines.append(f"  - phase {pid}: {', '.join(status['deferred_gaps'][pid])}")
    if status["human_review_gaps"]:
        lines.append("")
        lines.append("Quality gates still auto-approved (need a real human to watch the output):")
        lines.append("  - phases " + ", ".join(status["human_review_gaps"]))
    if status.get("missing_phases"):
        lines.append("")
        lines.append("Pipeline phases not yet built: " + ", ".join(status["missing_phases"]))
    return "\n".join(lines)
