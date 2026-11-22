"""Requirement trace. Reads the StrictDoc sources under docs/lifecycle (STK, SAF, SYS, HLR, LLR),
finds the tests that name each requirement (`covers: HLR-...`, `covers: LLR-...`) and the code that
implements each LLR (StrictDoc markers, `@relation(<LLR id>, scope=function)`, `class` or `file`),
and writes docs/lifecycle/08-traceability/matrix.md. With --check, exits 1 if:

- an active HLR or LLR says Test and no test names it, or does not say Test and has no
  VERIFICATION_NOTE with the reason;
- an active HLR has no active LLR child and no VERIFICATION_NOTE saying why HLR level is enough;
- an active LLR is not tagged in code (unless ALLOCATION is procedure), or a tag names an id that is
  not an active LLR, or a tag is malformed;
- a test names an id that is not an active requirement;
- a parent is missing or at the wrong level, a SYS has no STK or SAF parent, or a UID is used twice;
- an HLR or LLR id does not carry its file's item (llr-prs.sdoc holds LLR-PRS-nnn);
- a requirement breaks the grammar in docs/lifecycle/02-standards/requirements.sgra.

    python tools/trace.py [--check] [--html]

--html also runs StrictDoc and leaves the HTML in .local/strictdoc.
"""

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIFECYCLE = ROOT / "docs" / "lifecycle"
GRAMMAR = LIFECYCLE / "02-standards" / "requirements.sgra"
MATRIX = LIFECYCLE / "08-traceability" / "matrix.md"
TAG = re.compile(r"\b(?:HLR|LLR)-[A-Z][A-Z0-9]*-\d{3}\b")
TEST_GLOBS = ["tests/**/*.py", "frontend/test/**/*.ts", "frontend/test/**/*.tsx", "frontend/e2e/**/*.ts"]
# code that implements LLR; tests and tools/ are not searched for tags
CODE_GLOBS = ["flightmd_core/**/*.py", "api/**/*.py", "scripts/*.py", "frontend/lib/**/*.ts",
              "frontend/lib/**/*.tsx", "frontend/components/**/*.ts", "frontend/components/**/*.tsx",
              "frontend/app/**/*.tsx", "frontend/i18n/*.ts"]
RELATION = re.compile(r"@relation\(([^)]*)\)")
LLR_ID = re.compile(r"LLR-[A-Z][A-Z0-9]*-\d{3}")
SCOPES = ("file", "function", "class")
LEVELS = ("STK", "SAF", "SYS", "HLR", "LLR")
PARENT_LEVELS = {"STK": (), "SAF": (), "SYS": ("STK", "SAF"), "HLR": ("SYS",), "LLR": ("HLR",)}


@dataclass
class Req:
    uid: str
    level: str
    where: str
    fields: dict[str, str]
    parents: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return self.fields.get("STATUS", "")

    @property
    def title(self) -> str:
        return self.fields.get("TITLE", "")


def read_grammar() -> list[tuple[str, list[str] | None, bool]]:
    """REQUIREMENT fields in grammar order: (name, choices or None, required)."""
    out: list[tuple[str, list[str] | None, bool]] = []
    inside = False
    name = ""
    choices: list[str] | None = None
    for line in GRAMMAR.read_text(encoding="utf-8").splitlines():
        if line.startswith("- TAG: "):
            inside = line == "- TAG: REQUIREMENT"
        elif inside and (m := re.fullmatch(r"  - TITLE: (\w+)", line)):
            name = m[1]
        elif inside and (m := re.fullmatch(r"    TYPE: (\w+)(?:\((.*)\))?", line)):
            choices = [c.strip() for c in m[2].split(",")] if m[2] else None
        elif inside and (m := re.fullmatch(r"    REQUIRED: (True|False)", line)):
            out.append((name, choices, m[1] == "True"))
    return out


def read_node(lines: list[str], i: int, where: str) -> tuple[dict[str, str], list[str], int]:
    fields: dict[str, str] = {}
    parents: list[str] = []
    while i < len(lines) and lines[i].strip():
        line = lines[i]
        if line == "RELATIONS:":
            i += 1
            while i < len(lines) and lines[i].startswith(("- TYPE: ", "  ")):
                kind = lines[i].removeprefix("- TYPE: ")
                if lines[i].startswith("  ") or i + 1 == len(lines) or not lines[i + 1].startswith("  VALUE: "):
                    raise SystemExit(f"{where}:{i + 1}: cannot read this relation (- TYPE: then   VALUE:)")
                if kind == "Parent":
                    parents.append(lines[i + 1].removeprefix("  VALUE: ").strip())
                i += 2
                while i < len(lines) and lines[i].startswith("  ROLE: "):
                    i += 1
            continue
        m = re.fullmatch(r"([A-Z][A-Z0-9_]*): (.*)", line)
        if not m:
            raise SystemExit(f"{where}:{i + 1}: expected FIELD: value, got {line!r}")
        name, value = m[1], m[2]
        if value == ">>>":
            end = i + 1
            while end < len(lines) and lines[end] != "<<<":
                end += 1
            if end == len(lines):
                raise SystemExit(f"{where}:{i + 1}: {name} is never closed with <<<")
            value = "\n".join(lines[i + 1:end])
            i = end
        fields[name] = value
        i += 1
    return fields, parents, i


def read_sdoc(path: Path) -> list[Req]:
    rel = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.as_posix()
    lines = path.read_text(encoding="utf-8").splitlines()
    out = []
    i = 0
    while i < len(lines):
        tag = re.fullmatch(r"\[([A-Z_]+)\]", lines[i])
        # DOCUMENT and GRAMMAR hold no multi-line text, so their lines can be stepped over
        if not tag or tag[1] in ("DOCUMENT", "GRAMMAR"):
            i += 1
            continue
        start = i + 1
        fields, parents, i = read_node(lines, start, rel)
        if tag[1] == "REQUIREMENT":
            uid = fields.get("UID", "")
            prefix = uid.split("-", 1)[0]
            out.append(Req(uid, prefix if prefix in LEVELS else "", f"{rel}:{start}", fields, parents))
    return out


def requirements() -> list[Req]:
    reqs = []
    for path in sorted(LIFECYCLE.rglob("*.sdoc"), key=Path.as_posix):
        reqs += read_sdoc(path)
    return reqs


def coverage() -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    for pattern in TEST_GLOBS:
        # by posix string, so Windows and Linux give the same matrix
        for path in sorted(ROOT.glob(pattern), key=Path.as_posix):
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "covers:" not in line:
                    continue
                for uid in TAG.findall(line):
                    hits.setdefault(uid, []).append(f"{path.relative_to(ROOT).as_posix()}:{i}")
    return hits


def code_files() -> list[Path]:
    skip = {"__pycache__", "node_modules"}
    return [p for g in CODE_GLOBS for p in sorted(ROOT.glob(g), key=Path.as_posix) if p.is_file() and not skip & set(p.parts)]


def code_tags(files: list[Path] | None = None) -> tuple[dict[str, list[str]], list[str]]:
    """LLR id -> code locations tagged with it, and the malformed tags."""
    tags: dict[str, list[str]] = {}
    bad = []
    for path in code_files() if files is None else files:
        rel = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.as_posix()
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for m in RELATION.finditer(line):
                parts = [x.strip() for x in m[1].split(",")]
                ids = [x for x in parts if "=" not in x]
                opts = dict(x.split("=", 1) for x in parts if "=" in x)
                wrong = [x for x in ids if not LLR_ID.fullmatch(x)]
                if not ids or wrong or opts.get("scope") not in SCOPES or set(opts) - {"scope", "role"}:
                    bad.append(f"{rel}:{i}: malformed tag {m[0]} (needs LLR ids and scope={'|'.join(SCOPES)})")
                    continue
                for uid in ids:
                    tags.setdefault(uid, []).append(f"{rel}:{i}")
    return tags, bad


def methods(r: Req) -> set[str]:
    return {m.strip() for m in r.fields.get("VERIFICATION", "").split(",") if m.strip()}


def active_llr_children(reqs: list[Req]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for r in reqs:
        if r.level == "LLR" and r.status == "Active":
            for p in r.parents:
                out.setdefault(p, []).append(r.uid)
    return out


def problems(reqs: list[Req], hits: dict[str, list[str]], code: dict[str, list[str]],
             bad_tags: list[str]) -> list[str]:
    grammar = read_grammar()
    order = [name for name, _, _ in grammar]
    by_uid: dict[str, Req] = {}
    out = []
    for r in reqs:
        if not r.level:
            out.append(f"{r.where}: {r.uid or 'no UID'} has no known level prefix ({', '.join(LEVELS)})")
            continue
        if r.uid in by_uid:
            out.append(f"{r.where}: {r.uid} is also at {by_uid[r.uid].where}")
        by_uid[r.uid] = r
        unknown = [f for f in r.fields if f not in order]
        if unknown:
            out.append(f"{r.where}: {r.uid}: fields not in the grammar: {', '.join(unknown)}")
        elif list(r.fields) != sorted(r.fields, key=order.index):
            out.append(f"{r.where}: {r.uid}: fields out of grammar order")
        for name, choices, required in grammar:
            value = r.fields.get(name)
            if value is None:
                if required:
                    out.append(f"{r.where}: {r.uid}: {name} is required")
                continue
            if choices and any(v.strip() not in choices for v in value.split(",")):
                out.append(f"{r.where}: {r.uid}: {name} {value!r} is not one of {', '.join(choices)}")

    low = active_llr_children(reqs)
    for r in by_uid.values():
        if r.status == "Deleted":
            continue
        for p in r.parents:
            if p not in by_uid:
                out.append(f"{r.where}: {r.uid}: parent {p} does not exist")
            elif by_uid[p].level not in PARENT_LEVELS[r.level]:
                need = "/".join(PARENT_LEVELS[r.level])
                out.append(f"{r.where}: {r.uid}: parent {p} is {by_uid[p].level}, needs {need}")
            elif by_uid[p].status == "Deleted":
                out.append(f"{r.where}: {r.uid}: parent {p} is deleted")
        if r.level in ("STK", "SAF") and not r.fields.get("SOURCE"):
            out.append(f"{r.where}: {r.uid}: needs a SOURCE (ConOps section or hazard assessment failure condition)")
        if r.level in ("SYS", "HLR", "LLR") and not r.fields.get("VERIFICATION"):
            out.append(f"{r.where}: {r.uid}: needs a VERIFICATION method")
        if r.level in ("SYS", "HLR", "LLR") and not r.parents:
            out.append(f"{r.where}: {r.uid}: has no {'/'.join(PARENT_LEVELS[r.level])} parent")
        if r.level in ("HLR", "LLR"):
            # hlr-anl.sdoc -> ANL
            kind, _, item = Path(r.where.rsplit(":", 1)[0]).stem.partition("-")
            if kind.upper() != r.level or not r.uid.startswith(f"{r.level}-{item.upper()}-"):
                out.append(f"{r.where}: {r.uid}: a {r.level} lives in {r.level.lower()}-<item>.sdoc "
                           f"and is {r.level}-<ITEM>-nnn")
        if r.level in ("HLR", "LLR") and r.status == "Active":
            if "Test" in methods(r) and not hits.get(r.uid):
                out.append(f"{r.where}: {r.uid}: VERIFICATION says Test but no test names it (covers: {r.uid})")
            if "Test" not in methods(r) and not r.fields.get("VERIFICATION_NOTE"):
                out.append(f"{r.where}: {r.uid}: not verified by test, so needs a VERIFICATION_NOTE with the reason")
        if r.level == "HLR" and r.status == "Active" and not low.get(r.uid) and not r.fields.get("VERIFICATION_NOTE"):
            out.append(f"{r.where}: {r.uid}: no active LLR child, and no VERIFICATION_NOTE on why HLR level is enough")
        if (r.level == "LLR" and r.status == "Active" and not code.get(r.uid)
                and "procedure" not in r.fields.get("ALLOCATION", "")):
            out.append(f"{r.where}: {r.uid}: not tagged in code (@relation({r.uid}, scope=function))")

    out += bad_tags
    for uid in sorted(code):
        t = by_uid.get(uid)
        if t is None or t.level != "LLR":
            out.append(f"{code[uid][0]}: tag names {uid}, which is not an LLR")
        elif t.status != "Active":
            out.append(f"{code[uid][0]}: tag names {uid}, which is {t.status}")

    for uid in sorted(hits):
        r = by_uid.get(uid)
        if r is None or r.status == "Deleted":
            out.append(f"{hits[uid][0]}: names {uid}, which is {'deleted' if r else 'not a requirement'}")
    return out


def children(reqs: list[Req]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for r in reqs:
        for p in r.parents:
            out.setdefault(p, []).append(r.uid)
    return out


def cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def verified_by(r: Req, hits: dict[str, list[str]]) -> str:
    tests = "<br>".join(hits.get(r.uid, []))
    if "Test" not in methods(r):
        tests = (tests + "<br>" if tests else "") + "/".join(sorted(methods(r))).lower()
    return tests


def matrix(reqs: list[Req], hits: dict[str, list[str]], code: dict[str, list[str]], found: list[str]) -> str:
    kids = children(reqs)
    by_level: dict[str, list[Req]] = {}
    for r in reqs:
        by_level.setdefault(r.level, []).append(r)
    lines = ["# Traceability matrix", "",
             "Generated by `tools/trace.py` from the StrictDoc sources in `docs/lifecycle`. Do not edit; edit the",
             "`.sdoc` files or the tests and run `python tools/trace.py`. How the trace works is in `README.md`",
             "beside this file.", "",
             "| Level | Active | Proposed | Deleted |", "|---|---|---|---|"]
    for level in LEVELS:
        rs = by_level.get(level, [])
        if rs:
            counts = [sum(r.status == s for r in rs) for s in ("Active", "Proposed", "Deleted")]
            lines.append(f"| {level} | " + " | ".join(str(c) for c in counts) + " |")
    hlr = [r for r in by_level.get("HLR", []) if r.status == "Active"]
    llr = [r for r in by_level.get("LLR", []) if r.status == "Active"]
    low = active_llr_children(reqs)
    lines += ["", f"Active HLR: {len(hlr)}; named by a test: {sum(bool(hits.get(r.uid)) for r in hlr)}; "
              f"verified by review, analysis or demonstration only: {sum('Test' not in methods(r) for r in hlr)}; "
              f"with no LLR child (HLR level only): {sum(not low.get(r.uid) for r in hlr)}.", "",
              f"Active LLR: {len(llr)}; named by a test: {sum(bool(hits.get(r.uid)) for r in llr)}; "
              f"verified by review or analysis only: {sum('Test' not in methods(r) for r in llr)}; "
              f"tagged in code: {sum(bool(code.get(r.uid)) for r in llr)}. "
              f"Problems found by the check: {len(found)}.", "",
              "| Document | Active | Proposed | Deleted |", "|---|---|---|---|"]
    for src in sorted({r.where.split(":")[0] for r in reqs}):
        rs = [r for r in reqs if r.where.startswith(src + ":")]
        counts = [sum(r.status == s for r in rs) for s in ("Active", "Proposed", "Deleted")]
        lines.append(f"| `{src.removeprefix('docs/lifecycle/')}` | " + " | ".join(str(c) for c in counts) + " |")

    lines += ["", "## Open", ""]
    proposed = [r for r in reqs if r.status == "Proposed"]
    lonely = [r for r in by_level.get("SYS", []) if r.status == "Active" and not kids.get(r.uid)]
    unreached = [r for r in by_level.get("SAF", []) + by_level.get("STK", []) if not kids.get(r.uid)]
    untested = [r for r in hlr + llr if "Test" not in methods(r)]
    if not (proposed or lonely or unreached or untested or found):
        lines.append("Nothing open.")
    for r in proposed:
        lines.append(f"- {r.uid} ({r.level}, Proposed): {cell(r.title)}")
    for r in lonely:
        lines.append(f"- {r.uid}: active system requirement with no HLR yet")
    for r in unreached:
        lines.append(f"- {r.uid}: no system requirement traces to it")
    for r in untested:
        lines.append(f"- {r.uid}: no test ({'/'.join(sorted(methods(r))).lower()}): "
                     f"{cell(r.fields.get('VERIFICATION_NOTE', ''))}")
    for p in found:
        lines.append(f"- check: {cell(p)}")

    lines += ["", "## Needs and safety requirements to system requirements", "",
              "| Up | Status | Title | System requirements |", "|---|---|---|---|"]
    for r in by_level.get("STK", []) + by_level.get("SAF", []):
        down = ", ".join(sorted(kids.get(r.uid, []))) or "**none**"
        lines.append(f"| {r.uid} | {r.status} | {cell(r.title)} | {down} |")

    lines += ["", "## System requirements to HLR", "",
              "| SYS | Status | Title | Up | HLR |", "|---|---|---|---|---|"]
    for r in sorted(by_level.get("SYS", []), key=lambda r: r.uid):
        down = ", ".join(sorted(kids.get(r.uid, []))) or ("open" if r.status == "Proposed" else "**none**")
        lines.append(f"| {r.uid} | {r.status} | {cell(r.title)} | {', '.join(r.parents)} | {down} |")

    lines += ["", "## HLR to LLR and tests", "", "| HLR | Status | Title | Up | LLR | Verified by |",
              "|---|---|---|---|---|---|"]
    for r in by_level.get("HLR", []):
        down = ", ".join(sorted(kids.get(r.uid, []))) or ("HLR level" if r.fields.get("VERIFICATION_NOTE") else "-")
        lines.append(f"| {r.uid} | {r.status} | {cell(r.title)} | {', '.join(r.parents)} | {down} "
                     f"| {verified_by(r, hits) or '**none**'} |")

    lines += ["", "## LLR to code and tests", "", "| LLR | Status | Up | Code | Verified by |", "|---|---|---|---|---|"]
    for r in by_level.get("LLR", []):
        lines.append(f"| {r.uid} | {r.status} | {', '.join(r.parents)} | {'<br>'.join(code.get(r.uid, [])) or '-'} "
                     f"| {verified_by(r, hits) or '-'} |")
    return "\n".join(lines) + "\n"


def html() -> int:
    exe = shutil.which("strictdoc")
    if exe is None:
        print("strictdoc is not installed in this environment (pip install -r api/requirements-dev.txt)")
        return 1
    out = ROOT / ".local" / "strictdoc"
    cfg = LIFECYCLE / "08-traceability" / "strictdoc_config.py"
    # one process; the default worker pool eats a small laptops memory
    res = subprocess.run([exe, "export", str(LIFECYCLE), "--config", str(cfg), "--output-dir", str(out),
                          "--formats", "html", "--no-parallelization"], capture_output=True, text=True)
    if res.returncode != 0:
        print(res.stdout[-3000:], res.stderr[-3000:])
        return res.returncode
    print(f"html in {out / 'html' / 'index.html'}")
    return 0


def check() -> tuple[list[Req], dict[str, list[str]], dict[str, list[str]], list[str]]:
    reqs = requirements()
    hits = coverage()
    tags, bad_tags = code_tags()
    return reqs, hits, tags, problems(reqs, hits, tags, bad_tags)


def main() -> int:
    reqs, hits, tags, found = check()
    MATRIX.write_text(matrix(reqs, hits, tags, found), encoding="utf-8", newline="\n")

    counts = {lv: sum(r.level == lv for r in reqs) for lv in LEVELS}
    hlr = [r for r in reqs if r.level == "HLR" and r.status == "Active"]
    llr = [r for r in reqs if r.level == "LLR" and r.status == "Active"]
    print(", ".join(f"{n} {lv}" for lv, n in counts.items() if n) +
          f"; {sum(bool(hits.get(r.uid)) for r in hlr)} of {len(hlr)} active HLR named by a test; "
          f"{sum(bool(tags.get(r.uid)) for r in llr)} of {len(llr)} active LLR tagged in code")
    for p in found:
        print(f"  {p}")
    code = 1 if "--check" in sys.argv and found else 0
    if "--html" in sys.argv:
        code = html() or code
    return code


if __name__ == "__main__":
    sys.exit(main())
