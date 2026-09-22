"""The VS Code extension: its node tests, and the .vsix packager."""

import glob
import importlib.util
import json
import os
import shutil
import subprocess
import zipfile

import pytest

from conftest import REPO

VSCODE = os.path.join(REPO, "vscode")


def load_packager():
    spec = importlib.util.spec_from_file_location("package_vsix", os.path.join(VSCODE, "package_vsix.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_extension_node_tests():
    files = sorted(glob.glob(os.path.join(VSCODE, "test", "*.test.js")))
    r = subprocess.run(["node", "--test", *files], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_vsix_has_manifest_and_files_at_the_repo_version(tmp_path):
    pkg = load_packager()
    out = tmp_path / "x.vsix"
    ext_id, ver = pkg.build(str(out))
    version = open(os.path.join(REPO, "VERSION")).read().strip()
    assert (ext_id, ver) == ("jviegas6.claude-worksessions", version)
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        assert names == {"[Content_Types].xml", "extension.vsixmanifest", "extension/package.json",
                         "extension/extension.js", "extension/model.js"}
        manifest = z.read("extension.vsixmanifest").decode()
        assert 'Id="claude-worksessions" Version="{}" Publisher="jviegas6"'.format(version) in manifest
        assert json.loads(z.read("extension/package.json"))["version"] == version
        # every file the manifest's main and requires need is there
        assert json.loads(z.read("extension/package.json"))["main"] == "extension.js"


def test_packager_cli(tmp_path, capsys):
    pkg = load_packager()
    assert pkg.main([]) == 2
    assert "package_vsix.py OUT.vsix" in capsys.readouterr().err
    assert pkg.main([str(tmp_path / "y.vsix")]) == 0
    assert capsys.readouterr().out.startswith("jviegas6.claude-worksessions ")
