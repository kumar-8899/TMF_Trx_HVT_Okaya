# Build the LabVIEW Bridge EXE with g-cli (work-rule 5).
#
# Requires a Windows machine with LabVIEW + g-cli on PATH. Hosted CI runners do
# not have LabVIEW; run this on a self-hosted Windows runner. The CI `labview`
# job stays a placeholder until that runner exists.
#
# Usage:  ./build.ps1 [-Project Bridge.lvproj] [-BuildSpec "Bridge EXE"] [-Out ../../dist]

param(
    [string]$Project   = "$PSScriptRoot/Bridge.lvproj",
    [string]$BuildSpec = "Bridge EXE",
    [string]$Out       = "$PSScriptRoot/../../dist"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command g-cli -ErrorAction SilentlyContinue)) {
    Write-Error "g-cli not found. Install LabVIEW + g-cli on this (self-hosted) runner."
    exit 1
}

if (-not (Test-Path $Project)) {
    Write-Error "Project not found: $Project. Create the DQMH Bridge project per README.md (the Python stub at backend/tools/lv_stub.py is the contract)."
    exit 1
}

New-Item -ItemType Directory -Force -Path $Out | Out-Null

Write-Host "Building '$BuildSpec' from $Project ..."
g-cli --labview-version 2021 -- BuildPackedLibraryAndExe `
    --project $Project `
    --build-spec $BuildSpec `
    --out $Out

Write-Host "Bridge EXE built to $Out"
