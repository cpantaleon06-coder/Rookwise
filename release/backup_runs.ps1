<#
.SYNOPSIS
Zip the gitignored runs/ folder into backups/runs-YYYYMMDD-HHMM.zip.

.DESCRIPTION
Same output as release/backup_runs.py: the archive keeps paths relative to the repository
root (runs/..., forward slashes), and its SHA-256 goes beside it in
runs-YYYYMMDD-HHMM.zip.sha256 in the sha256sum format ("<hex>  <file name>"). Both paths
and the hash are printed. An archive that already exists is never overwritten.

runs/ holds cassettes with prompt text. The backup is local only: backups/ is not in
.gitignore yet, so add it there before running "git add -A".

.EXAMPLE
powershell -ExecutionPolicy Bypass -File release/backup_runs.ps1
powershell -ExecutionPolicy Bypass -File release/backup_runs.ps1 -Root C:\path -OutDir C:\out
#>
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$Root = (Resolve-Path -LiteralPath $Root).Path
$runs = Join-Path $Root "runs"
if (-not (Test-Path -LiteralPath $runs -PathType Container)) {
    Write-Output "no runs/ folder under $Root"
    exit 1
}
if ($OutDir -eq "") { $OutDir = Join-Path $Root "backups" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$OutDir = (Resolve-Path -LiteralPath $OutDir).Path

$name = "runs-{0}.zip" -f (Get-Date -Format "yyyyMMdd-HHmm")
$archive = Join-Path $OutDir $name
if (Test-Path -LiteralPath $archive) {
    Write-Output "$archive already exists; nothing was written"
    exit 1
}
$partial = "$archive.partial"
if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Confirm:$false }

# Entries are written one by one so their names use forward slashes on every .NET version.
$zip = [System.IO.Compression.ZipFile]::Open($partial, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    $prefix = $Root.TrimEnd('\', '/').Length + 1
    Get-ChildItem -LiteralPath $runs -Recurse -File -Force | Sort-Object FullName | ForEach-Object {
        $entry = $_.FullName.Substring($prefix).Replace('\', '/')
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $zip, $_.FullName, $entry, [System.IO.Compression.CompressionLevel]::Optimal
        ) | Out-Null
    }
}
finally {
    $zip.Dispose()
}
Move-Item -LiteralPath $partial -Destination $archive

$digest = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
$checksum = "$archive.sha256"
[System.IO.File]::WriteAllText($checksum, "$digest  $name`n", (New-Object System.Text.ASCIIEncoding))

Write-Output "archive: $archive"
Write-Output "sha256:  $digest"
Write-Output "sha256 file: $checksum"
