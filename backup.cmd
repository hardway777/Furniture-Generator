@echo off
rem Whole-project backup mirror into Backup\ (gitignored).
rem Run before any risky operation: geometry edits, batch renames, git surgery.
rem Overwrites changed files, keeps files that were deleted from the project
rem since the last backup (no /MIR - a backup that deletes is not a backup).
rem
rem Updated 2026-09-28: first version. Extend the /XD list when a new folder
rem appears that must never be copied (large caches, build junk).

robocopy "%~dp0." "%~dp0Backup" /E /XD "%~dp0Backup" "__pycache__" ".idea" /NFL /NDL /NJH /NJS /NP

rem robocopy codes 0-7 are success (1 = files copied); 8+ is a real failure.
if %ERRORLEVEL% GEQ 8 (
    echo BACKUP FAILED, robocopy code %ERRORLEVEL%
    exit /b 1
)
echo BACKUP OK, robocopy code %ERRORLEVEL%
