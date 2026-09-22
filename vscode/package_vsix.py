#!/usr/bin/env python3
"""Build the VS Code extension as a .vsix, with no npm or vsce: a .vsix is a zip holding a
manifest, a content-types list and the extension files under extension/.

  python3 vscode/package_vsix.py OUT.vsix

The extension takes the repo's VERSION, so install.sh can tell when it needs reinstalling.
"""

import json
import os
import sys
import zipfile
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = ["package.json", "extension.js", "model.js"]

CONTENT_TYPES = """<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension=".json" ContentType="application/json"/>
  <Default Extension=".js" ContentType="application/javascript"/>
  <Default Extension=".vsixmanifest" ContentType="text/xml"/>
</Types>
"""

MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011">
  <Metadata>
    <Identity Language="en-US" Id="{name}" Version="{version}" Publisher="{publisher}"/>
    <DisplayName>{display}</DisplayName>
    <Description xml:space="preserve">{description}</Description>
    <Categories>Other</Categories>
    <Properties>
      <Property Id="Microsoft.VisualStudio.Code.Engine" Value="{engine}"/>
    </Properties>
  </Metadata>
  <Installation>
    <InstallationTarget Id="Microsoft.VisualStudio.Code"/>
  </Installation>
  <Dependencies/>
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true"/>
  </Assets>
</PackageManifest>
"""


def version():
    with open(os.path.join(HERE, "..", "VERSION")) as fh:
        return fh.read().strip()


def build(out):
    with open(os.path.join(HERE, "package.json")) as fh:
        pkg = json.load(fh)
    pkg["version"] = version()
    manifest = MANIFEST.format(
        name=escape(pkg["name"]), version=escape(pkg["version"]), publisher=escape(pkg["publisher"]),
        display=escape(pkg["displayName"]), description=escape(pkg["description"]),
        engine=escape(pkg["engines"]["vscode"]))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("extension.vsixmanifest", manifest)
        z.writestr("extension/package.json", json.dumps(pkg, indent=2) + "\n")
        for f in FILES[1:]:
            z.write(os.path.join(HERE, f), "extension/" + f)
    return "{}.{}".format(pkg["publisher"], pkg["name"]), pkg["version"]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python3 vscode/package_vsix.py OUT.vsix", file=sys.stderr)
        return 2
    ext_id, ver = build(argv[0])
    print("{} {}".format(ext_id, ver))
    return 0


if __name__ == "__main__":
    sys.exit(main())
