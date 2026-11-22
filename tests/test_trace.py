import re

from tools import trace


def test_requirements_trace_to_tests_and_code():
    reqs, hits, tags, found = trace.check()
    assert reqs, "no requirements found under docs/lifecycle"
    assert found == [], "\n" + "\n".join(found)


def test_committed_matrix_is_current():
    reqs, hits, tags, found = trace.check()
    want = trace.matrix(reqs, hits, tags, found)
    have = trace.MATRIX.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert have == want, "docs/lifecycle/08-traceability/matrix.md is stale: run python tools/trace.py"


def test_a_tag_with_no_scope_is_reported(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text('def f():\n    """@relation(LLR-INT-001)"""\n', encoding="utf-8")
    tags, bad = trace.code_tags([f])
    assert tags == {}
    assert len(bad) == 1 and re.search(r"mod\.py:2: malformed tag", bad[0])


def test_checker_finds_a_missing_parent_and_an_untested_llr(tmp_path):
    doc = tmp_path / "llr-int.sdoc"
    doc.write_text(
        "[DOCUMENT]\nTITLE: t\n\n"
        "[REQUIREMENT]\nUID: LLR-INT-900\nSTATUS: Active\nTITLE: t\nSTATEMENT: s\n"
        "VERIFICATION: Test\nALLOCATION: intake\nRELATIONS:\n- TYPE: Parent\n  VALUE: HLR-INT-900\n",
        encoding="utf-8")
    found = trace.problems(trace.read_sdoc(doc), {}, {}, [])
    text = "\n".join(found)
    assert "parent HLR-INT-900 does not exist" in text
    assert "VERIFICATION says Test but no test names it" in text
    assert "not tagged in code" in text
