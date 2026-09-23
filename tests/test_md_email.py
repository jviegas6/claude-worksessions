"""bin/claude-md-email: Markdown → email HTML with inline styles, onto the clipboard."""

import io
import os
import shutil
import subprocess
import types

import pytest

from conftest import load_script


@pytest.fixture
def mail():
    return load_script("claude-md-email")


class Runs:
    """Stand-in for subprocess.run: records calls, answers with `rc` and `out`."""
    def __init__(self, rc=0, out="", err=""):
        self.calls, self.rc, self.out, self.err = [], rc, out, err

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        return types.SimpleNamespace(returncode=self.rc, stdout=self.out, stderr=self.err)


def test_parse_css_reads_tag_rules(mail):
    rules = mail.parse_css("<style>\n/* note */ body { color: #000; margin: 4px }\n"
                           "th, TD { border: 1px } th { background: red; }\n.cls { x: y } a:hover { z: 1 }\n</style>")
    assert rules == {"body": "color: #000; margin: 4px", "th": "border: 1px; background: red", "td": "border: 1px"}


def test_inline_merges_styles_and_wraps_in_the_body_rule(mail):
    rules = {"body": "color: #000; margin: 24px; max-width: 900px", "p": "font-size: 11pt", "br": "x: 1"}
    html = mail.inline('<p>a</p>\n<p style="color: red" id="x">b<br/></p><span>c</span>', rules)
    assert html == ('<div style="color: #000">\n<p style="font-size: 11pt">a</p>\n'
                    '<p style="font-size: 11pt; color: red" id="x">b<br style="x: 1"/></p><span>c</span></div>\n')
    assert mail.inline("<p>a</p>", {"p": "x: 1"}) == '<p style="x: 1">a</p>'   # no body rule: no wrapper


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
def test_render_with_the_real_stylesheet(mail, tmp_path):
    md = tmp_path / "n.md"
    md.write_text("# T\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")
    html = mail.render(str(md))
    assert html.startswith('<div style="font-family: Calibri')
    assert "margin: 24px" not in html and "max-width" not in html
    assert '<th style="border: 1px solid #999' in html and "background: #e8eef7" in html


def test_render_errors(mail, tmp_path, monkeypatch):
    md = tmp_path / "n.md"
    md.write_text("x")
    monkeypatch.setattr(mail.shutil, "which", lambda n: None)
    with pytest.raises(SystemExit, match="pandoc is not installed"):
        mail.render(str(md))
    monkeypatch.setattr(mail.shutil, "which", lambda n: "/x/" + n)
    monkeypatch.setattr(mail.subprocess, "run", Runs(rc=1, err="bad input"))
    with pytest.raises(SystemExit, match="pandoc failed: bad input"):
        mail.render(str(md))
    monkeypatch.setattr(mail.subprocess, "run", Runs(out="<p>hi</p>"))
    css = tmp_path / "s.css"
    css.write_text("p { color: #000 }")
    assert mail.render(str(md), str(css)) == '<p style="color: #000">hi</p>'


def test_system(mail, monkeypatch):
    monkeypatch.setattr(mail.sys, "platform", "darwin")
    assert mail.system() == "mac"
    monkeypatch.setattr(mail.sys, "platform", "linux")
    real_open = open
    for text, want in [("Linux 5.15 microsoft-standard-WSL2", "wsl"), ("Linux 6.1 generic", "linux")]:
        monkeypatch.setattr("builtins.open", lambda p, *a, t=text, **k:
                            io.StringIO(t) if p == "/proc/version" else real_open(p, *a, **k))
        assert mail.system() == want
    monkeypatch.setattr("builtins.open", lambda p, *a, **k: (_ for _ in ()).throw(OSError()) if p == "/proc/version" else real_open(p, *a, **k))
    assert mail.system() == "linux"


def test_copy_on_each_system(mail, monkeypatch):
    runs = Runs(out="C:\\Temp\\it's\\m.html\n")
    monkeypatch.setattr(mail.subprocess, "run", runs)
    assert mail.copy("<p>x</p>", "x", "mac") == "osascript"
    cmd, kw = runs.calls[-1]
    assert cmd[:3] == ["osascript", "-l", "JavaScript"] and cmd[-2].endswith("m.html") and cmd[-1].endswith("m.txt")
    assert kw["input"] is None

    assert mail.copy("<p>x</p>", "x", "wsl") == "powershell.exe"
    assert runs.calls[-2][0][:2] == ["wslpath", "-w"]
    assert "ReadAllText('C:\\Temp\\it''s\\m.html'" in runs.calls[-1][0][-1]

    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(mail.shutil, "which", lambda n: "/usr/bin/" + n)
    assert mail.copy("<p>x</p>", "x", "linux") == "wl-copy"
    assert runs.calls[-1][1]["input"] == "<p>x</p>"
    monkeypatch.delenv("WAYLAND_DISPLAY")
    assert mail.copy("<p>x</p>", "x", "linux") == "xclip"
    monkeypatch.setattr(mail.shutil, "which", lambda n: None)
    with pytest.raises(SystemExit, match="no clipboard tool"):
        mail.copy("<p>x</p>", "x", "linux")
    monkeypatch.setattr(mail.subprocess, "run", Runs(rc=1, err="denied"))
    with pytest.raises(SystemExit, match="copying failed: denied"):
        mail.copy("<p>x</p>", "x", "mac")
    monkeypatch.setattr(mail, "system", lambda: "mac")
    monkeypatch.setattr(mail.subprocess, "run", Runs())
    assert mail.copy("<p>x</p>", "x") == "osascript"


def test_open_page_on_each_system(mail, monkeypatch, tmp_path):
    monkeypatch.setattr(mail.tempfile, "gettempdir", lambda: str(tmp_path))
    runs = Runs()
    monkeypatch.setattr(mail.subprocess, "run", runs)
    p = mail.open_page("<p>x</p>", "note", "mac")
    assert p == str(tmp_path / "md-email" / "note.html")
    assert '<body style="background: #fff">' in open(p).read()
    assert runs.calls[-1][0] == ["open", p]
    monkeypatch.setattr(mail.shutil, "which", lambda n: "/usr/bin/wslview")
    mail.open_page("<p>x</p>", "note", "wsl")
    assert runs.calls[-1][0][0] == "wslview"
    monkeypatch.setattr(mail.shutil, "which", lambda n: None)
    mail.open_page("<p>x</p>", "note", "wsl")
    assert runs.calls[-1][0][0] == "explorer.exe"
    mail.open_page("<p>x</p>", "note", "linux")
    assert runs.calls[-1][0][0] == "xdg-open"
    monkeypatch.setattr(mail, "system", lambda: "linux")
    mail.open_page("<p>x</p>", "note")


def test_main(mail, monkeypatch, tmp_path, capsys):
    md = tmp_path / "Weekly note.md"
    md.write_text("# Hi\n")
    monkeypatch.setattr(mail, "render", lambda f: "<h1>Hi</h1>")
    copied = []
    monkeypatch.setattr(mail, "copy", lambda h, p: copied.append((h, p)))
    monkeypatch.setattr(mail, "open_page", lambda h, t: "/tmp/" + t + ".html")
    assert mail.main([str(md)]) == 0
    assert copied == [("<h1>Hi</h1>", "# Hi\n")]
    assert "copied Weekly note.md for email" in capsys.readouterr().out
    mail.main([str(md), "--html", "-"])
    assert capsys.readouterr().out == "<h1>Hi</h1>"
    out = tmp_path / "o.html"
    mail.main([str(md), "--html", str(out)])
    assert "<title>Weekly note</title>" in out.read_text()
    mail.main([str(md), "--open"])
    assert "opened /tmp/Weekly note.html" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="no such file"):
        mail.main([str(tmp_path / "missing.md")])


def test_command_line_prints_html(tmp_path):
    if shutil.which("pandoc") is None:
        pytest.skip("pandoc not installed")
    md = tmp_path / "n.md"
    md.write_text("Hello **there**\n")
    r = subprocess.run([os.path.join(os.path.dirname(__file__), "..", "bin", "claude-md-email"),
                        str(md), "--html", "-"], capture_output=True, text=True)
    assert r.returncode == 0 and "<strong>there</strong>" in r.stdout
