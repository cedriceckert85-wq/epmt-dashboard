# Test Spec — Process Tree Kill (Windows)

Harness (Phase 00): run ProcessRunner against tests/fakes/fake_tree.py with a
2 s timeout on the REAL Windows box.

PASS requires:
- direct child terminated
- detached/re-parented grandchild PID (from --pidfile) no longer alive OR
  ProcessResult.cleanup_incomplete == True (fail-closed path taken)
- cleanup_incomplete == True forces phase BLOCKED per docs/EXIT_CODES.md
- no pipe handles left open (handle count via harness before/after)
