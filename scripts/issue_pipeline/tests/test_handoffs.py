from scripts.issue_pipeline.handoffs import parse_handoff


def test_review_handoff_parses_numbered_findings_with_colons():
    text = "\n".join(
        [
            "REVIEW_HANDOFF",
            "Verdict: FIX FIRST",
            "Reviewed-SHA: def329ff0000000000000000000000000000000000",
            "Base-SHA: abcdef1234567890",
            "Tasks-checked: 1/1",
            "Pytest: passed",
            "Verification: npm run test",
            "Findings:",
            "1. match-count-inherit-label — DEFAULT_DISPLAY_MATCH_COUNT in frontend-demo/app/components/AdvancedRetrievalDrawer.tsx",
            "2. frontend-demo/app/components/AdvancedRetrievalDrawer.tsx: detail with: colons",
            "3. frontend-demo/app/components/AdvancedRetrievalDrawer.tsx: third path mention",
        ]
    )
    fields = parse_handoff(text, "REVIEW_HANDOFF")
    findings = fields["Findings"]
    assert "match-count-inherit-label" in findings
    assert "DEFAULT_DISPLAY_MATCH_COUNT" in findings
    assert findings.count("frontend-demo/app/components/AdvancedRetrievalDrawer.tsx") >= 3
    assert "Verdict" not in findings
    assert fields["Verdict"] == "FIX FIRST"
    assert fields["Reviewed-SHA"].startswith("def329ff")


def test_findings_boundary_stops_at_blank_line():
    text = "\n".join(
        [
            "REVIEW_HANDOFF",
            "Verdict: FIX FIRST",
            "Reviewed-SHA: abcdef1234567890",
            "Base-SHA: abcdef1234567890",
            "Tasks-checked: 1/1",
            "Pytest: passed",
            "Verification: scripts/issue-pipeline verify -- pytest backend/tests -q",
            "Findings:",
            "1. path/to/file.tsx: label `foo` — detail with: colons",
            "2. second item still in findings",
            "",
            "Notes: should not be in findings",
        ]
    )
    fields = parse_handoff(text, "REVIEW_HANDOFF")
    assert "second item" in fields["Findings"]
    assert "Notes" not in fields["Findings"]
