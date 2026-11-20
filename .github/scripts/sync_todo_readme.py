#!/usr/bin/env python3
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(os.environ.get("LUFFY_ROOT", ".")).resolve()
README = ROOT / "README.md"
TITLE = "### 📝 Complete TODO List"
KNOWN_CHANGED = {
    "luffy/deepscaler/utils.py",
    "luffy/verl/verl/protocol.py",
}
EXPECTED_COUNTS = {
    "luffy/deepscaler/utils.py": 11,
    "luffy/verl/verl/protocol.py": 7,
}
ENTRY_RE = re.compile(
    r"^- \[ \] \*\*(?P<path>.+?):(?P<line>\d+)\*\* - (?P<message>.*?)\s*$"
)
TODO_RE = re.compile(r"#\s*TODO\b\s*:?[ \t-]*(?P<message>.*?)[ \t]*$")


def rel_posix(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def extract_todos(path: Path):
    records = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for lineno, raw_line in enumerate(text.splitlines(), 1):
        if "TODO" not in raw_line:
            continue
        match = TODO_RE.search(raw_line)
        if not match:
            continue
        message = (match.group("message") or "").strip()
        if not message:
            message = "TODO"
        records.append((rel_posix(path), lineno, message))
    return records


all_by_path = {}
all_records = []
python_files = sorted(
    (p for p in ROOT.rglob("*.py") if p.is_file() and ".git" not in p.parts),
    key=rel_posix,
)
for path in python_files:
    records = extract_todos(path)
    if records:
        rp = rel_posix(path)
        all_by_path[rp] = records
        all_records.extend(records)

print(f"Scanned {len(python_files)} Python files and {len(all_records)} TODO records")
for rp in sorted(all_by_path):
    print(f"TODO_FILE {rp} {len(all_by_path[rp])}")

changed_py = set(KNOWN_CHANGED)
try:
    subprocess.run(
        ["git", "fetch", "--no-tags", "origin", "main:refs/remotes/origin/main"],
        cwd=ROOT, check=False, capture_output=True, text=True, timeout=90,
    )
    diff_names = set()
    for revision_range in ("origin/main...HEAD", "origin/main..HEAD"):
        output = subprocess.check_output(
            ["git", "diff", "--name-only", revision_range],
            cwd=ROOT, text=True, timeout=90, stderr=subprocess.PIPE,
        )
        diff_names.update(
            line.strip().replace("\\", "/")
            for line in output.splitlines()
            if line.strip().endswith(".py")
        )
    if diff_names:
        changed_py = diff_names | KNOWN_CHANGED
    else:
        changed_py |= KNOWN_CHANGED
except Exception as exc:
    print(f"Git diff discovery unavailable; using known main-to-dev paths: {exc!r}")
    changed_py |= KNOWN_CHANGED

changed_py = {p.replace("\\", "/").removeprefix("./") for p in changed_py if p}
print("CHANGED_PY " + ",".join(sorted(changed_py)))
for path in sorted(changed_py):
    records = all_by_path.get(path, [])
    expected = EXPECTED_COUNTS.get(path)
    print(f"APPLY {path} current={len(records)} expected={expected}")
    for record in records:
        print(f"  {record[0]}:{record[1]} - {record[2]}")
    if expected is not None and len(records) != expected:
        print(f"WARNING: {path} count {len(records)} != investigated count {expected}")

original = README.read_text(encoding="utf-8")
lines = original.splitlines()
if TITLE not in lines:
    raise SystemExit("Required exact README title line is missing")
title_index = lines.index(TITLE)

section_end = len(lines)
in_fence = False
for i in range(title_index + 1, len(lines)):
    stripped = lines[i].lstrip()
    if stripped.startswith("```") or stripped.startswith("~~~"):
        in_fence = not in_fence
    if not in_fence and lines[i].startswith("## "):
        section_end = i
        break

interior = lines[title_index + 1:section_end]
first_entry = None
last_entry = None
for i, line in enumerate(interior):
    if ENTRY_RE.match(line):
        if first_entry is None:
            first_entry = i
        last_entry = i

prefix_extra = []
suffix_extra = []
middle_extra = []
existing_entries = []
for i, line in enumerate(interior):
    match = ENTRY_RE.match(line)
    if match:
        path = match.group("path")
        lineno = int(match.group("line"))
        if path not in changed_py:
            existing_entries.append((path, lineno, line))
    elif line.strip():
        if first_entry is not None and i < first_entry:
            prefix_extra.append(line)
        elif last_entry is not None and i > last_entry:
            suffix_extra.append(line)
        else:
            middle_extra.append(line)

combined = list(existing_entries)
for path in sorted(changed_py):
    for _, lineno, message in all_by_path.get(path, []):
        rendered = f"- [ ] **{path}:{lineno}** - {message}"
        combined.append((path, lineno, rendered))

combined.sort(key=lambda item: (item[0], item[1], item[2]))
rendered_entries = [item[2] for item in combined]

new_interior = [""]
new_interior.extend(prefix_extra)
new_interior.extend(rendered_entries)
new_interior.extend(middle_extra)
new_interior.extend(suffix_extra)
new_interior.append("")
new_lines = lines[:title_index + 1] + new_interior + lines[section_end:]
updated = "\n".join(new_lines)
if original.endswith("\n"):
    updated += "\n"

if updated.count(TITLE) != 1:
    raise SystemExit("README title invariant failed")
if not rendered_entries:
    raise SystemExit("Refusing to write an empty TODO list")

if updated != original:
    import difflib
    diff_text = "".join(difflib.unified_diff(
        original.splitlines(keepends=True),
        updated.splitlines(keepends=True),
        fromfile="a/README.md", tofile="b/README.md", n=3,
    ))
    print("===== README DIFF START =====")
    print(diff_text[:100000])
    print("===== README DIFF END =====")
    README.write_text(updated, encoding="utf-8")
    print(f"WROTE README with {len(rendered_entries)} entries")
else:
    print(f"README unchanged; {len(rendered_entries)} entries already current")
