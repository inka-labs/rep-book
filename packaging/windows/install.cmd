@echo off
rem Installs or updates Rep Book for you (no administrator rights needed). Double-click it.
title Rep Book installer
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0app\packaging\windows\install.ps1" -Source "%~dp0app"
