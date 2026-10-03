@echo off
rem Builds BUILD\FurnitureGenerator-<version>.zip (version read from blender_manifest.toml).
rem The archive root holds the files flat - no nested folder (extension format).
rem Verifies the archive byte-identical to the source before calling itself done.
rem Arguments pass through, so `build_zip.cmd --test` writes the -TEST archive.
python "%~dp0build_zip.py" %*
