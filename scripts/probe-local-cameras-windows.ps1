[CmdletBinding()]
param(
    [int]$MaxIndex = 5
)

$ErrorActionPreference = "Stop"

& (Join-Path $PSScriptRoot "probe-local-cameras.ps1") -MaxIndex $MaxIndex
