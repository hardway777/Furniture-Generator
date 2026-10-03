"""Build BUILD/FurnitureGenerator-<version>.zip from Files/.

The zip is what Blender installs via 'Install from Disk' (extension format), so the
archive root must hold the addon files flat - modules, blender_manifest.toml,
gpl-3.0.txt and the textures/ folder. No nested folder, no parent wrapper.

The version is read from blender_manifest.toml (the extension manifest), not
bl_info - bl_info is gone from this addon.

`--test` writes BUILD/FurnitureGenerator-<version>-TEST.zip instead: a build the user
drags into Blender to try a branch must not overwrite the archive of the release that is
installed, because Blender's overwrite is what makes the two distinguishable at all.
The release archive is only ever written by a plain run, on master, after the merge.

Every entry is verified byte-identical to the source after the zip is closed -
a build that silently differs from the source is worse than no build.

Usage: python build_zip.py [--test]   (or build_zip.cmd, which passes its arguments on)
"""
import io
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(ROOT, "Files")
BUILD = os.path.join(ROOT, "BUILD")


def read_version():
    src = io.open(os.path.join(PKG, "blender_manifest.toml"), encoding="utf-8").read()
    m = re.search(r'^version\s*=\s*"([^"]+)"', src, re.MULTILINE)
    if not m:
        sys.exit("could not read the version string from blender_manifest.toml")
    return m.group(1)


def collect_files():
    names = []
    for f in sorted(os.listdir(PKG)):
        if f.endswith(".py") or f in ("blender_manifest.toml", "gpl-3.0.txt"):
            names.append((f, os.path.join(PKG, f)))
    texdir = os.path.join(PKG, "textures")
    if os.path.isdir(texdir):
        for f in sorted(os.listdir(texdir)):
            # Zip names always use forward slashes, whatever the host OS uses.
            names.append(("textures/" + f, os.path.join(texdir, f)))
    return names


def main():
    # Only one switch, parsed by hand: argparse would be the heaviest thing in the repo
    # for a single boolean, and a mistyped argument must not silently build a release zip.
    unknown = [a for a in sys.argv[1:] if a != "--test"]
    if unknown:
        sys.exit(f"unknown argument(s): {unknown}\nusage: python build_zip.py [--test]")
    is_test = "--test" in sys.argv[1:]

    version = read_version()
    files = collect_files()
    os.makedirs(BUILD, exist_ok=True)
    out = os.path.join(BUILD, f"FurnitureGenerator-{version}{'-TEST' if is_test else ''}.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, path in files:
            z.write(path, arcname=arc)
    # Verify: every entry byte-identical to the source.
    bad = []
    with zipfile.ZipFile(out) as z:
        entries = z.namelist()
        for arc, path in files:
            if z.read(arc) != open(path, "rb").read():
                bad.append(arc)
    print(f"built {out}" + ("  [TEST build]" if is_test else ""))
    print(f"entries: {len(entries)} (modules + manifest + textures)")
    if bad:
        sys.exit(f"BYTE MISMATCH in: {bad}")
    print("all entries byte-identical to the source: True")


if __name__ == "__main__":
    main()
