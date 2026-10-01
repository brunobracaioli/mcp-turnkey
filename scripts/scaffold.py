"""Scaffold a new MCP server from ``template/``.

Usage:
    python scripts/scaffold.py --name acme-crm [--title "Acme CRM"] [--dest DIR] [--force]

Copies the living template, renaming every ``bootstrap`` token (package, slug, display
name, paths), regenerates the tenant namespace uuid, stamps the initial migration with
the current UTC time and lists the remaining ``SCAFFOLD:`` decisions. Standard library
only, so it runs before any virtualenv exists. Spec: docs/specs/scaffold.md.

Exit codes: 0 ok · 1 a template token survived the rename · 2 invalid input.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "template"

TEMPLATE_TOKEN = "bootstrap"  # noqa: S105 - the template name, not a secret
TEMPLATE_NAMESPACE = "00000000-0000-4000-8000-0000b0075742"
TEMPLATE_MIGRATION = "00000000000000_init.sql"
# A decision marker opens its line (after a comment/quote prefix); mentions do not count.
SCAFFOLD_MARKER = re.compile(r"^\s*(?:#|>|--|//)?\s*SCAFFOLD:")

_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
_NAME_MIN, _NAME_MAX = 2, 40
# Titles land inside Python/TOML/JSON string literals: no quotes or backslashes.
_TITLE_RE = re.compile(r"^[^\W_][\w .&+-]{0,59}$")

EXIT_OK, EXIT_LEFTOVER, EXIT_INVALID = 0, 1, 2

_SKIP_DIRS = frozenset(
    {
        ".git",
        "venv",
        ".venv",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".vercel",
        ".secrets",
        "htmlcov",
    }
)
_SKIP_FILES = frozenset({".env", ".env.local", ".mcp.json", ".coverage"})
_SKIP_SUFFIXES = (".pyc", ".pyo")


class ScaffoldError(Exception):
    """Invalid input: nothing was written."""


@dataclass(frozen=True)
class Names:
    kebab: str
    snake: str
    title: str


@dataclass
class Report:
    dest: Path
    files: int = 0
    markers: list[str] = field(default_factory=list)
    leftovers: list[str] = field(default_factory=list)


def validate_name(name: str) -> str:
    """Return the kebab-case name, or raise ScaffoldError."""
    if not _NAME_MIN <= len(name) <= _NAME_MAX or not _NAME_RE.fullmatch(name):
        raise ScaffoldError(
            f"--name must be kebab-case, {_NAME_MIN}-{_NAME_MAX} chars "
            "(lowercase letters, digits, single hyphens), e.g. acme-crm"
        )
    if name == "mcp" or name.startswith("mcp-"):
        raise ScaffoldError("--name must not start with 'mcp-' (the prefix is added for you)")
    if TEMPLATE_TOKEN in name:
        raise ScaffoldError(f"--name must not contain '{TEMPLATE_TOKEN}'")
    return name


def default_title(name: str) -> str:
    return " ".join(part.capitalize() for part in name.split("-"))


def validate_title(title: str) -> str:
    title = title.strip()
    if not _TITLE_RE.fullmatch(title):
        raise ScaffoldError(
            "--title must be 1-60 chars of letters, digits, spaces and . & + - "
            "(no quotes), starting with a letter or digit"
        )
    if TEMPLATE_TOKEN in title.lower():
        raise ScaffoldError(f"--title must not contain '{TEMPLATE_TOKEN}'")
    return title


def replacements(names: Names, namespace: str) -> list[tuple[str, str]]:
    """Token -> value pairs, longest/most specific first."""
    return [
        (TEMPLATE_NAMESPACE, namespace),
        (f"mcp_{TEMPLATE_TOKEN}", f"mcp_{names.snake}"),
        (f"mcp-{TEMPLATE_TOKEN}", f"mcp-{names.kebab}"),
        (f"MCP {TEMPLATE_TOKEN.capitalize()}", f"MCP {names.title}"),
        (TEMPLATE_TOKEN.capitalize(), names.title),
        (TEMPLATE_TOKEN, names.snake),
    ]


def _apply(text: str, pairs: Sequence[tuple[str, str]]) -> str:
    for old, new in pairs:
        text = text.replace(old, new)
    return text


def _skipped(path: Path) -> bool:
    if any(part in _SKIP_DIRS or part.endswith(".egg-info") for part in path.parts):
        return True
    name = path.name
    if name in _SKIP_FILES or name.endswith(_SKIP_SUFFIXES):
        return True
    # Local env overrides (.env.production.local, …) never travel; .env.example does.
    return name.startswith(".env.") and name.endswith(".local")


def resolve_dest(dest: Path | None, names: Names, *, template_root: Path) -> Path:
    bootstrap_root = template_root.parent.resolve()
    # Default: a sibling of this repository (…/mcp-<name>).
    target = (dest or bootstrap_root.parent / f"mcp-{names.kebab}").resolve()
    if target == bootstrap_root or bootstrap_root in target.parents:
        raise ScaffoldError(f"--dest must be outside {bootstrap_root}")
    return target


def scaffold(
    names: Names,
    dest: Path,
    *,
    template_dir: Path = TEMPLATE_DIR,
    force: bool = False,
    now: datetime | None = None,
) -> Report:
    """Copy ``template_dir`` into ``dest`` with every token replaced."""
    if dest.exists() and any(dest.iterdir()) and not force:
        raise ScaffoldError(f"{dest} is not empty (use --force to write into it)")
    stamp = (now or datetime.now(tz=timezone.utc)).strftime("%Y%m%d%H%M%S")
    pairs = replacements(names, str(uuid.uuid4()))
    path_pairs = [(TEMPLATE_MIGRATION, f"{stamp}_init.sql"), *pairs]
    report = Report(dest=dest)

    for source in sorted(template_dir.rglob("*")):
        relative = source.relative_to(template_dir)
        if source.is_dir() or _skipped(relative):
            continue
        target = dest / Path(*(_apply(part, path_pairs) for part in relative.parts))
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            text = source.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            shutil.copyfile(source, target)  # binary: verbatim
        else:
            target.write_text(_apply(text, pairs), encoding="utf-8")
        shutil.copymode(source, target)  # keeps hooks executable
        report.files += 1

    _inspect(report)
    return report


def _inspect(report: Report) -> None:
    """Collect SCAFFOLD markers and any template token that survived."""
    for path in sorted(report.dest.rglob("*")):
        relative = path.relative_to(report.dest)
        if _skipped(relative):
            continue
        if TEMPLATE_TOKEN in str(relative).lower():
            report.leftovers.append(f"{relative} (path)")
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(lines, start=1):
            if TEMPLATE_TOKEN in line.lower():
                report.leftovers.append(f"{relative}:{number}")
            if SCAFFOLD_MARKER.match(line):
                report.markers.append(f"{relative}:{number}: {line.strip()}")


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scaffold a new MCP server from template/.")
    parser.add_argument("--name", required=True, help="kebab-case, without 'mcp-' (acme-crm)")
    parser.add_argument("--title", help="display title (default: Title Case of --name)")
    parser.add_argument("--dest", type=Path, help="output dir (default: ../mcp-<name>)")
    parser.add_argument("--force", action="store_true", help="write into a non-empty --dest")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse(argv)
    try:
        kebab = validate_name(args.name)
        names = Names(
            kebab=kebab,
            snake=kebab.replace("-", "_"),
            title=validate_title(args.title or default_title(kebab)),
        )
        dest = resolve_dest(args.dest, names, template_root=TEMPLATE_DIR)
        report = scaffold(names, dest, force=args.force)
    except ScaffoldError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INVALID

    print(f"Created {report.dest} ({report.files} files) — package mcp_{names.snake}.")
    if report.leftovers:
        print("error: template tokens survived the rename:", file=sys.stderr)
        for leftover in report.leftovers:
            print(f"  {leftover}", file=sys.stderr)
        return EXIT_LEFTOVER
    print(f"\n{len(report.markers)} SCAFFOLD decisions to make:")
    for marker in report.markers:
        print(f"  {marker}")
    print(
        "\nNext:\n"
        f"  cd {report.dest}\n"
        "  python -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'\n"
        "  pytest -q && ruff check . && mypy src\n"
        "  git init && fill docs/specs/ before replacing the example 'items' slice\n"
        "  python scripts/gen_keys.py   # fresh keys for THIS server"
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
