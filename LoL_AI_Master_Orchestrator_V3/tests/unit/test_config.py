from pathlib import Path
def test_all_phase_files_exist():
    root=Path(__file__).resolve().parents[2]
    for i in range(21):
        assert (root/"phases"/f"phase-{i:02d}.yaml").exists()
