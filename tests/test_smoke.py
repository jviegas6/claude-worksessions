def test_scripts_import(audit, search):
    assert audit.DEFAULT_ROOT.endswith("work_sessions")
    assert callable(search.main)


def test_every_command_is_executable():
    """A command committed without its executable bit breaks the moment a checkout rewrites it."""
    import os
    import subprocess
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    listed = subprocess.run(["git", "ls-files", "-s", "bin"], cwd=repo, capture_output=True, text=True).stdout
    modes = {line.split("\t")[1]: line.split()[0] for line in listed.splitlines()}
    assert modes and all(m == "100755" for m in modes.values()), modes
