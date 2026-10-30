#Requires -Version 5.1
<#
.SYNOPSIS
    Publishes CharacterLock Studio (main branch + v1.0.0 tag + GitHub Release assets)
    to a public GitHub repository named CharacterLock-Studio and updates SUBMISSION_READY.md.
#>
[CmdletBinding()]
param(
    [string]$RepoName = "CharacterLock-Studio",
    [string]$ReleaseTag = "v1.0.0",
    [string]$ReleaseTitle = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$EmDash = [char]0x2014
if (-not $ReleaseTitle) {
    $ReleaseTitle = "CharacterLock Studio v1.0.0 $EmDash Open Source Higgsfield Edition"
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DistDir  = Join-Path (Split-Path $RepoRoot -Parent) "dist_package"
$ZipPath  = Join-Path $DistDir "CharacterLockStudio-Windows-x64.zip"
$ShaPath  = Join-Path $DistDir "CharacterLockStudio-Windows-x64.zip.sha256"
$DemoPath = Join-Path $RepoRoot "examples\characterlock-studio-demo.mp4"

# Ensure Git and GitHub CLI are discoverable
$ExtraPaths = @(
    (Join-Path $env:ProgramFiles "GitHub CLI"),
    (Join-Path $env:ProgramFiles "Git\cmd")
)
foreach ($p in $ExtraPaths) {
    if ((Test-Path $p) -and ($env:PATH -notlike "*$p*")) {
        $env:PATH = "$p;$env:PATH"
    }
}

$ghCmd = Get-Command gh -ErrorAction SilentlyContinue
if (-not $ghCmd) {
    throw "GitHub CLI (gh) was not found. Install GitHub CLI from https://cli.github.com/ and re-run."
}

Write-Host "========================================================================" -ForegroundColor Cyan
Write-Host "  CHARACTERLOCK STUDIO - GITHUB REPOSITORY & RELEASE PUBLISHER" -ForegroundColor Cyan
Write-Host "========================================================================" -ForegroundColor Cyan

# Step 1: Verify or obtain GitHub authentication
$authOk = $false
try {
    & gh auth status 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { $authOk = $true }
} catch {}

if (-not $authOk) {
    try {
        $gcmAccounts = (& git credential-manager github list 2>$null)
        if ($LASTEXITCODE -eq 0 -and $gcmAccounts) {
            $credInput = "protocol=https`nhost=github.com`n`n"
            $filled = $credInput | & git credential fill 2>$null
            $pwLine = $filled | Where-Object { $_ -like "password=*" } | Select-Object -First 1
            if ($pwLine) {
                $token = $pwLine.Substring(9).Trim()
                if ($token) {
                    $token | & gh auth login --hostname github.com --git-protocol https --with-token
                    if ($LASTEXITCODE -eq 0) { $authOk = $true }
                }
            }
        }
    } catch {}
}

if (-not $authOk) {
    Write-Host "`n[1/5] Opening browser for GitHub login (one-time code copied to clipboard - press Ctrl+V and click 'Authorize github')..." -ForegroundColor Yellow
    "`n" | & gh auth login --hostname github.com --git-protocol https --web --clipboard
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub authentication was cancelled or failed."
    }
}

& gh auth setup-git --hostname github.com 2>$null | Out-Null
$GhUser = (& gh api user --jq ".login").Trim()
if (-not $GhUser) {
    throw "Could not resolve authenticated GitHub username."
}
Write-Host "[1/5] Authenticated on GitHub as: $GhUser" -ForegroundColor Green

# Step 2: Create or update public GitHub repository
Push-Location $RepoRoot
try {
    $FullSlug = "$GhUser/$RepoName"
    $RepoUrl  = "https://github.com/$FullSlug"
    $Description = "Local-first AI character production studio powered by ComfyUI & Comfy SDK - Character Sheet, Dataset, Video, Voice, and Motion Swap."

    Write-Host "[2/5] Ensuring public repository $FullSlug exists..." -ForegroundColor Cyan
    $repoExists = $false
    try {
        & gh repo view $FullSlug --json name 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { $repoExists = $true }
    } catch {}

    if (-not $repoExists) {
        & gh repo create $FullSlug --public --description $Description
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to create public repository $FullSlug."
        }
    } else {
        & gh repo edit $FullSlug --visibility public --accept-visibility-change-consequences --description $Description 2>$null | Out-Null
    }

    $remotes = (& git remote)
    if ($remotes -contains "origin") {
        & git remote set-url origin "$RepoUrl.git"
    } else {
        & git remote add origin "$RepoUrl.git"
    }

    # Update SUBMISSION_READY.md with live verified GitHub username before final push
    $SubPath = Join-Path $RepoRoot "SUBMISSION_READY.md"
    if (Test-Path $SubPath) {
        $subRaw = [System.IO.File]::ReadAllText($SubPath, [System.Text.Encoding]::UTF8)
        $subUpdated = $subRaw.Replace("<SEU_USUARIO_GITHUB>", $GhUser).Replace("<YOUR_GITHUB_USERNAME>", $GhUser)
        if ($subUpdated -ne $subRaw) {
            [System.IO.File]::WriteAllText($SubPath, $subUpdated, (New-Object System.Text.UTF8Encoding($false)))
            & git add "SUBMISSION_READY.md"
            & git commit -m "docs: record verified GitHub repository and release URLs in SUBMISSION_READY.md"
            & git tag -f -a $ReleaseTag -m $ReleaseTitle
        }
    }

    Write-Host "[3/5] Pushing main branch and tag $ReleaseTag to $RepoUrl..." -ForegroundColor Cyan
    & git push -u origin main --force
    if ($LASTEXITCODE -ne 0) { throw "Failed to push main branch." }
    & git push origin $ReleaseTag --force
    if ($LASTEXITCODE -ne 0) { throw "Failed to push tag $ReleaseTag." }

    # Step 4: Publish GitHub Release + Windows x64 ZIP + SHA256 + Demo MP4
    Write-Host "[4/5] Publishing GitHub Release '$ReleaseTitle' and uploading assets..." -ForegroundColor Cyan
    if (-not (Test-Path $ZipPath)) {
        throw "Windows distribution archive not found at: $ZipPath"
    }
    $shaLine = if (Test-Path $ShaPath) { (Get-Content $ShaPath -Raw).Trim() } else { (Get-FileHash -Algorithm SHA256 $ZipPath).Hash.ToLower() }
    $zipSizeMb = [math]::Round((Get-Item $ZipPath).Length / 1MB, 2)

    $NotesFile = Join-Path ([System.IO.Path]::GetTempPath()) "cls-release-notes-$ReleaseTag.md"
    $ReleaseNotes = @"
## $ReleaseTitle

> **Create once. Keep the character. Produce everything.**
> Built for the [Comfy.org Open Source Higgsfield Competition](https://comfy.org/open-source-higgsfield).

### Highlights
- **Character Lab & 9-View Character Sheet** - Lock facial geometry, hair, wardrobe, and multi-angle identity with Qwen Image 2.1 + Multi-Angle LoRA.
- **Persistent Character Dataset** - Curated per-character multi-expression & multi-angle gallery with automatic reference packaging.
- **Video Studio (MiniMax H3)** - Identity-consistent video generation with local VRAM supervision (`AIModelMemoryManager`).
- **Voice Studio (OmniVoice)** - Expressive multilingual neural voice cloning & synthesis linked directly to each character profile.
- **Motion Swap (5s Validated Pipeline)** - Replace a target performer in real video with a locked Studio character while preserving camera framing, background lighting, and body performance via MiniMax H3 Ref2VA + Character Swap LoRA.
- **Official Comfy SDK + Local Engine Stack** - Supervised local `ComfyUI` + `comfy-api-proxy` execution with zero cloud lock-in.

### Windows x64 Standalone Package (`CharacterLockStudio-Windows-x64.zip`)
1. Extract `CharacterLockStudio-Windows-x64.zip` to any folder (starts with a clean library and seeds all 16 redistributable API workflows automatically).
2. Point to an existing `ComfyUI_windows_portable` directory (auto-detected at `%USERPROFILE%\ComfyUI_windows_portable` or `C:\ComfyUI_windows_portable`, or set in `.env`).
3. Run `Setup-Models.bat` (or `CharacterLockStudio.exe --setup-models`) to verify/download modular model weights with resumable HTTP Range + SHA-256 verification.
4. Launch `CharacterLockStudio.exe` - opens `http://127.0.0.1:8000`.

### Checksum (`SHA-256`)
``````text
$shaLine
Size: $zipSizeMb MiB
``````

See [`README.md`]($RepoUrl/blob/main/README.md) and [`THIRD_PARTY_LICENSES.md`]($RepoUrl/blob/main/THIRD_PARTY_LICENSES.md) for full documentation and model/custom-node license terms.
"@
    [System.IO.File]::WriteAllText($NotesFile, $ReleaseNotes, (New-Object System.Text.UTF8Encoding($false)))

    $Assets = @($ZipPath)
    if (Test-Path $ShaPath)  { $Assets += $ShaPath }
    if (Test-Path $DemoPath) { $Assets += $DemoPath }

    $relExists = $false
    try {
        & gh release view $ReleaseTag --repo $FullSlug 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { $relExists = $true }
    } catch {}

    if (-not $relExists) {
        & gh release create $ReleaseTag @Assets --repo $FullSlug --title $ReleaseTitle --notes-file $NotesFile
        if ($LASTEXITCODE -ne 0) { throw "Failed to create GitHub Release $ReleaseTag." }
    } else {
        & gh release edit $ReleaseTag --repo $FullSlug --title $ReleaseTitle --notes-file $NotesFile
        & gh release upload $ReleaseTag @Assets --repo $FullSlug --clobber
        if ($LASTEXITCODE -ne 0) { throw "Failed to upload assets to GitHub Release $ReleaseTag." }
    }

    # Step 5: Unauthenticated HTTP 200 public check
    Write-Host "[5/5] Verifying public unauthenticated access..." -ForegroundColor Cyan
    $ReleaseUrl = "$RepoUrl/releases/tag/$ReleaseTag"
    $ZipUrl     = "$RepoUrl/releases/download/$ReleaseTag/CharacterLockStudio-Windows-x64.zip"
    $DemoUrl    = "$RepoUrl/releases/download/$ReleaseTag/characterlock-studio-demo.mp4"

    $r1 = Invoke-WebRequest -Uri $RepoUrl -UseBasicParsing -Method Head -TimeoutSec 20
    $r2 = Invoke-WebRequest -Uri $ReleaseUrl -UseBasicParsing -Method Head -TimeoutSec 20

    Write-Host "========================================================================" -ForegroundColor Green
    Write-Host "  PUBLICATION VERIFIED (HTTP $($r1.StatusCode) / HTTP $($r2.StatusCode))" -ForegroundColor Green
    Write-Host "  GITHUB URL  : $RepoUrl" -ForegroundColor Green
    Write-Host "  RELEASE URL : $ReleaseUrl" -ForegroundColor Green
    Write-Host "  ZIP URL     : $ZipUrl" -ForegroundColor Green
    Write-Host "  DEMO URL    : $DemoUrl" -ForegroundColor Green
    Write-Host "  SUBMISSION  : $SubPath" -ForegroundColor Green
    Write-Host "========================================================================" -ForegroundColor Green
} finally {
    Pop-Location
}
