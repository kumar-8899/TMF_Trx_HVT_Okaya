@echo off
REM Launch the interactive app scaffolder (secure distribution P-b2).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0new_app.ps1" %*
