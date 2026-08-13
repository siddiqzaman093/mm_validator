"""The shipped findings sample must represent every rule that fired.

A high-volume rule must not bury the others within its category — in
particular the Dependencies engine's per-rule INFO summaries, which are the
user's only on-screen proof that a rule was understood and executed.
"""
from validator.models import Finding, Severity, ValidationReport


def _f(rule_id, severity, i):
    return Finding(
        severity=severity, category="Lookup/Dependency", sheet="Basic Data",
        row=i, field="f", sap_field="F", message=f"{rule_id} #{i}",
        rule_id=rule_id,
    )


def test_every_rule_id_survives_sampling():
    rep = ValidationReport(file_name="t.xlsx")
    # One rule floods the category…
    for i in range(6000):
        rep.add(_f("LKP_DEPENDENCY", Severity.ERROR, i))
    # …while the transparency lines are few and only INFO.
    for i in range(8):
        rep.add(_f("LKP_DEPENDENCY_INFO", Severity.INFO, i))
    rep.add(_f("LKP_DEPENDENCY_UNPARSED", Severity.WARNING, 1))

    shipped = rep.top_findings(ValidationReport.MAX_FINDINGS_JSON)
    ids = {f.rule_id for f in shipped}
    assert "LKP_DEPENDENCY_INFO" in ids, "rule summaries were buried by violations"
    assert "LKP_DEPENDENCY_UNPARSED" in ids
    # All 8 summaries fit — they are far below the per-category cap.
    assert sum(1 for f in shipped if f.rule_id == "LKP_DEPENDENCY_INFO") == 8


def test_counts_and_totals_still_cover_everything():
    rep = ValidationReport(file_name="t.xlsx")
    for i in range(3000):
        rep.add(_f("A", Severity.ERROR, i))
    for i in range(10):
        rep.add(_f("B", Severity.WARNING, i))
    d = rep.to_dict()
    assert d["counts"]["error"] == 3000 and d["counts"]["warning"] == 10
    assert d["findings_total"] == 3010
    cat = {c["name"]: c for c in d["category_counts"]}["Lookup/Dependency"]
    assert cat["total"] == 3010          # true totals, not sample sizes


def test_small_reports_are_shipped_whole():
    rep = ValidationReport(file_name="t.xlsx")
    for i in range(50):
        rep.add(_f("A", Severity.ERROR, i))
    assert len(rep.to_dict()["findings"]) == 50
    assert rep.to_dict()["findings_truncated"] is False
