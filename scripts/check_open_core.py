"""Task 1: prove the open core has no HARD dependency on the commercial code.

If anything that stays public imports a module that becomes private without handling its absence, the published
pip and npm packages break the moment the split lands. An import guarded by `try/except ImportError` is fine:
that is exactly how an open build is meant to discover that it has no billing.
"""

import ast
from pathlib import Path

ROOT = Path(r"C:\Projects\jev-mod")
PRIVATE_MODULES = {"billing", "hosted", "demo"}
PRIVATE_FILES = {
    ROOT / "jevmod" / "api" / "billing.py",
    ROOT / "jevmod" / "api" / "hosted.py",
    ROOT / "jevmod" / "api" / "demo.py",
}


def guarded_imports(tree: ast.AST) -> set[int]:
    """Line numbers of imports inside a try whose handler catches ImportError."""
    safe: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        catches = any(
            (isinstance(h.type, ast.Name) and h.type.id in {"ImportError", "ModuleNotFoundError", "Exception"})
            or h.type is None
            for h in node.handlers
        )
        if not catches:
            continue
        for stmt in node.body:
            for sub in ast.walk(stmt):
                if isinstance(sub, (ast.Import, ast.ImportFrom)):
                    safe.add(sub.lineno)
    return safe


hard, soft, checked = [], [], 0
for f in sorted((ROOT / "jevmod").rglob("*.py")):
    if f in PRIVATE_FILES or "__pycache__" in f.parts:
        continue
    checked += 1
    tree = ast.parse(f.read_text(encoding="utf-8"))
    safe = guarded_imports(tree)
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
        elif isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        for t in names:
            if t.split(".")[-1] in PRIVATE_MODULES and "api" in t:
                rel = f"{f.relative_to(ROOT).as_posix()}:{node.lineno}"
                (soft if node.lineno in safe else hard).append(f"{rel} imports {t}")

print(f"checked {checked} public module(s)")
for line in soft:
    print(f"  optional, handles ImportError: {line}")
if hard:
    print("HARD DEPENDENCY, the split would break the published package:")
    for line in hard:
        print("  " + line)
else:
    print("clean: no public module requires billing, hosted or demo")
