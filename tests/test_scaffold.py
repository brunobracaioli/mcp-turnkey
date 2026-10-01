"""scripts/scaffold.py — contract from docs/specs/scaffold.md."""

from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import scaffold

NAMES = scaffold.Names(kebab="acme-crm", snake="acme_crm", title="Acme CRM")
FIXED_NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def _texts(root: Path) -> dict[Path, str]:
    out = {}
    for path in root.rglob("*"):
        if path.is_file():
            try:
                out[path.relative_to(root)] = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
    return out


@pytest.fixture
def generated(tmp_path: Path) -> Path:
    dest = tmp_path / "mcp-acme-crm"
    report = scaffold.scaffold(NAMES, dest, now=FIXED_NOW)
    assert report.leftovers == []
    return dest


class TestValidation:
    @pytest.mark.parametrize("name", ["acme", "acme-crm", "a1", "x-2-y"])
    def test_valid_names(self, name: str) -> None:
        assert scaffold.validate_name(name) == name

    @pytest.mark.parametrize(
        "name",
        [
            "a",
            "Acme",
            "acme_crm",
            "-acme",
            "acme-",
            "acme--crm",
            "mcp-acme",
            "mcp",
            "my-bootstrap",
            "a" * 41,
        ],
    )
    def test_invalid_names(self, name: str) -> None:
        with pytest.raises(scaffold.ScaffoldError):
            scaffold.validate_name(name)

    def test_default_title(self) -> None:
        assert scaffold.default_title("acme-crm") == "Acme Crm"

    @pytest.mark.parametrize(
        "title", ['Bad "quote"', "back\\slash", "", "x" * 61, "Bootstrap Thing"]
    )
    def test_invalid_titles(self, title: str) -> None:
        with pytest.raises(scaffold.ScaffoldError):
            scaffold.validate_title(title)

    def test_cli_rejects_invalid_input_with_exit_2(self) -> None:
        assert scaffold.main(["--name", "Bad_Name"]) == scaffold.EXIT_INVALID

    def test_dest_inside_this_repository_is_refused(self) -> None:
        with pytest.raises(scaffold.ScaffoldError):
            scaffold.resolve_dest(scaffold.ROOT / "out", NAMES, template_root=scaffold.TEMPLATE_DIR)

    def test_default_dest_is_a_sibling_of_this_repository(self) -> None:
        dest = scaffold.resolve_dest(None, NAMES, template_root=scaffold.TEMPLATE_DIR)
        assert dest == scaffold.ROOT.parent / "mcp-acme-crm"

    def test_non_empty_dest_requires_force(self, tmp_path: Path) -> None:
        (tmp_path / "keep.txt").write_text("x")
        with pytest.raises(scaffold.ScaffoldError):
            scaffold.scaffold(NAMES, tmp_path)
        scaffold.scaffold(NAMES, tmp_path, force=True)
        assert (tmp_path / "keep.txt").read_text() == "x"


class TestOutput:
    def test_package_paths_are_renamed(self, generated: Path) -> None:
        assert (generated / "src" / "mcp_acme_crm" / "server.py").is_file()
        assert (generated / "docs" / "specs" / "mcp-acme-crm.md").is_file()
        assert (generated / "supabase" / "migrations" / "20260102030405_init.sql").is_file()
        assert not (generated / "src" / "mcp_bootstrap").exists()

    def test_no_template_token_survives(self, generated: Path) -> None:
        for relative, text in _texts(generated).items():
            assert "bootstrap" not in str(relative).lower()
            assert "bootstrap" not in text.lower(), relative

    def test_identity_values_are_replaced(self, generated: Path) -> None:
        config = (generated / "src" / "mcp_acme_crm" / "config.py").read_text()
        assert 'SERVICE_SLUG = "acme_crm"' in config
        assert 'SERVICE_DISPLAY_NAME = "MCP Acme CRM"' in config
        assert 'name = "mcp-acme-crm"' in (generated / "pyproject.toml").read_text()

    def test_each_scaffold_gets_its_own_tenant_namespace(self, tmp_path: Path) -> None:
        def namespace(dest: Path) -> str:
            scaffold.scaffold(NAMES, dest)
            text = (dest / "src" / "mcp_acme_crm" / "application" / "authserver.py").read_text()
            line = next(ln for ln in text.splitlines() if ln.startswith("_TENANT_NAMESPACE"))
            return line

        first, second = namespace(tmp_path / "a"), namespace(tmp_path / "b")
        assert first != second
        assert scaffold.TEMPLATE_NAMESPACE not in first

    def test_local_secrets_and_caches_are_never_copied(self, tmp_path: Path) -> None:
        template = tmp_path / "template"
        (template / ".secrets").mkdir(parents=True)
        (template / ".secrets" / "upstream_token.json").write_text("{}")
        (template / ".env.local").write_text("X=1")
        (template / ".env.example").write_text("X=")
        (template / "__pycache__").mkdir()
        (template / "__pycache__" / "m.cpython-310.pyc").write_bytes(b"\x00")
        dest = tmp_path / "out"
        scaffold.scaffold(NAMES, dest, template_dir=template)
        assert sorted(p.name for p in dest.rglob("*")) == [".env.example"]

    def test_binary_files_are_copied_verbatim(self, tmp_path: Path) -> None:
        template = tmp_path / "template"
        template.mkdir()
        blob = b"\x89PNG\r\n\x1a\n\xff\xfe bootstrap \x00"
        (template / "icon.png").write_bytes(blob)
        scaffold.scaffold(NAMES, tmp_path / "out", template_dir=template)
        assert (tmp_path / "out" / "icon.png").read_bytes() == blob

    def test_executable_bits_are_preserved(self, generated: Path) -> None:
        hook = generated / ".claude" / "hooks" / "pre-bash-guard.sh"
        assert hook.stat().st_mode & stat.S_IXUSR

    def test_scaffold_markers_are_reported(self, tmp_path: Path) -> None:
        report = scaffold.scaffold(NAMES, tmp_path / "out")
        assert any("config.py" in marker for marker in report.markers)
        assert not any(marker.startswith("CLAUDE.md") for marker in report.markers)


@pytest.mark.skipif(
    importlib.util.find_spec("mcp") is None or importlib.util.find_spec("respx") is None,
    reason="the template's runtime/dev dependencies are not installed",
)
def test_generated_project_passes_its_own_suite(generated: Path) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST")}
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=generated,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
