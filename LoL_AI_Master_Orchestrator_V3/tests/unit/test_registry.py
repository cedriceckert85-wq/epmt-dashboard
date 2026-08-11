from orchestrator import test_registry

def test_registry_loads_and_is_valid():
    tests=test_registry.load("test_registry.yaml")
    assert len(tests)>=40

def test_registry_covers_all_phase_tests():
    tests=test_registry.load("test_registry.yaml")
    assert test_registry.coverage_gaps(tests)==[]
