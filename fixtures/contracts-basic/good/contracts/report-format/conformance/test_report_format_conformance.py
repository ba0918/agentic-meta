"""Conformance tests for the report-format contract (fixture).

These run as plain pytest files when pytest is pointed at this directory.
They check a sample artifact against the contract's required structure.
"""

SAMPLE_REPORT = """\
# Report: sample subject

## Result

pass

## Evidence

- the sample observation
"""


def test_report_starts_with_the_required_heading():
    assert SAMPLE_REPORT.splitlines()[0].startswith("# Report:")


def test_report_contains_a_result_section_with_a_valid_outcome():
    assert "## Result" in SAMPLE_REPORT
    body_after_result = SAMPLE_REPORT.split("## Result", 1)[1]
    assert any(word in body_after_result for word in ("pass", "fail", "blocked"))


def test_report_contains_an_evidence_section_with_at_least_one_item():
    assert "## Evidence" in SAMPLE_REPORT
    evidence = SAMPLE_REPORT.split("## Evidence", 1)[1]
    assert any(line.lstrip().startswith("- ") for line in evidence.splitlines())
