def test_scripts_import(audit, search):
    assert audit.DEFAULT_ROOT.endswith("work_sessions")
    assert callable(search.main)
