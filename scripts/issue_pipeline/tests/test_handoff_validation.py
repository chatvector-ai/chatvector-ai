from scripts.issue_pipeline.handoff_validation import pytest_result_passed


def test_pytest_summary_formats_are_accepted():
    assert pytest_result_passed("passed")
    assert pytest_result_passed("passed 10")
    assert pytest_result_passed("1434 passed, 4 skipped")
    assert pytest_result_passed("Pytest: 1434 passed, 4 skipped")
    assert not pytest_result_passed("failed: 1 error")
    assert not pytest_result_passed("")
