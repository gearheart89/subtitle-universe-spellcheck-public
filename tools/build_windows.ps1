param(
    [string]$PythonExecutable = "python"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$expectedPyInstallerVersion = "6.22.3"

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "The Windows executable must be built on Windows."
}

Push-Location $projectRoot
try {
    $actualPyInstallerVersion = (& $PythonExecutable -c "import PyInstaller; print(PyInstaller.__version__)").Trim()
    if ($LASTEXITCODE -ne 0 -or $actualPyInstallerVersion -ne $expectedPyInstallerVersion) {
        throw "Install the pinned build dependency with: $PythonExecutable -m pip install -r requirements-build.txt"
    }

    $version = (& $PythonExecutable -c "from app import subtitle_cleanup; print(subtitle_cleanup.SCRIPT_VERSION)").Trim()
    if ($LASTEXITCODE -ne 0 -or -not $version) {
        throw "Could not read the application version."
    }

    $architecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString().ToLowerInvariant()
    $distributionName = "SubtitleUniverseSpellcheck"
    $distributionFolder = Join-Path $projectRoot "dist\$distributionName"
    $artifactFolder = Join-Path $projectRoot "artifacts"
    $artifactBaseName = "$distributionName-$version-windows-$architecture"
    $zipPath = Join-Path $artifactFolder "$artifactBaseName.zip"
    $checksumPath = "$zipPath.sha256"

    & $PythonExecutable -m PyInstaller `
        --noconfirm `
        --clean `
        --onedir `
        --console `
        --paths (Join-Path $projectRoot "app") `
        --name $distributionName `
        --distpath (Join-Path $projectRoot "dist") `
        --workpath (Join-Path $projectRoot "build\work") `
        --specpath (Join-Path $projectRoot "build") `
        (Join-Path $projectRoot "app\subtitle_gui.py")
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed."
    }

    $baseDestination = Join-Path $distributionFolder "dictionaries\base"
    $docsDestination = Join-Path $distributionFolder "docs"
    $licensesDestination = Join-Path $distributionFolder "licenses"
    New-Item -ItemType Directory -Force -Path $baseDestination | Out-Null
    New-Item -ItemType Directory -Force -Path $docsDestination | Out-Null
    New-Item -ItemType Directory -Force -Path $licensesDestination | Out-Null

    Copy-Item -LiteralPath (Join-Path $projectRoot "dictionaries\base\american_words.txt") -Destination $baseDestination
    Copy-Item -LiteralPath (Join-Path $projectRoot "dictionaries\base\british_words.txt") -Destination $baseDestination
    Copy-Item -LiteralPath (Join-Path $projectRoot "dictionaries\base\README.md") -Destination $baseDestination
    Copy-Item -LiteralPath (Join-Path $projectRoot "dictionaries\base\SCOWL-COPYRIGHT.txt") -Destination $baseDestination
    Copy-Item -LiteralPath (Join-Path $projectRoot "docs\USER_GUIDE.md") -Destination $docsDestination
    Copy-Item -LiteralPath (Join-Path $projectRoot "LICENSE") -Destination $distributionFolder
    Copy-Item -LiteralPath (Join-Path $projectRoot "README.md") -Destination $distributionFolder

    $pythonLicensePath = (& $PythonExecutable -c "from pathlib import Path; import sys; print(Path(sys.base_prefix) / 'LICENSE.txt')").Trim()
    $pyInstallerLicensePath = (& $PythonExecutable -c "from importlib.metadata import distribution; d = distribution('pyinstaller'); p = next(p for p in d.files if str(p).replace('\\', '/').endswith('/licenses/COPYING.txt')); print(d.locate_file(p))").Trim()
    Copy-Item -LiteralPath $pythonLicensePath -Destination (Join-Path $licensesDestination "PYTHON-LICENSE.txt")
    Copy-Item -LiteralPath $pyInstallerLicensePath -Destination (Join-Path $licensesDestination "PYINSTALLER-COPYING.txt")

    $executablePath = Join-Path $distributionFolder "$distributionName.exe"
    $reportedVersion = (& $executablePath --version).Trim()
    if ($LASTEXITCODE -ne 0 -or $reportedVersion -ne "Subtitle Universe Spellcheck $version") {
        throw "Built executable version smoke test failed. Expected $version; received '$reportedVersion'."
    }

    $requiredReleasePaths = @(
        $executablePath,
        (Join-Path $distributionFolder "README.md"),
        (Join-Path $distributionFolder "LICENSE"),
        (Join-Path $docsDestination "USER_GUIDE.md"),
        (Join-Path $baseDestination "american_words.txt"),
        (Join-Path $baseDestination "british_words.txt"),
        (Join-Path $baseDestination "README.md"),
        (Join-Path $baseDestination "SCOWL-COPYRIGHT.txt"),
        (Join-Path $licensesDestination "PYTHON-LICENSE.txt"),
        (Join-Path $licensesDestination "PYINSTALLER-COPYING.txt")
    )
    foreach ($requiredPath in $requiredReleasePaths) {
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
            throw "Required release file is missing: $requiredPath"
        }
    }

    $forbiddenRuntimePaths = @(
        (Join-Path $distributionFolder "dictionaries\user"),
        (Join-Path $distributionFolder "dictionaries\universes"),
        (Join-Path $distributionFolder "dictionaries\options.ini"),
        (Join-Path $distributionFolder "dictionaries\gui_theme.json"),
        (Join-Path $distributionFolder "dictionaries\session_state.json"),
        (Join-Path $distributionFolder "dictionaries\session_log.jsonl"),
        (Join-Path $distributionFolder "launch gui.txt"),
        (Join-Path $distributionFolder "launch cli.txt")
    )
    foreach ($forbiddenPath in $forbiddenRuntimePaths) {
        if (Test-Path -LiteralPath $forbiddenPath) {
            throw "Forbidden runtime data was included in the release: $forbiddenPath"
        }
    }

    New-Item -ItemType Directory -Force -Path $artifactFolder | Out-Null
    if (Test-Path -LiteralPath $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }
    if (Test-Path -LiteralPath $checksumPath) {
        Remove-Item -LiteralPath $checksumPath -Force
    }
    Compress-Archive -LiteralPath $distributionFolder -DestinationPath $zipPath -CompressionLevel Optimal

    $hash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $([IO.Path]::GetFileName($zipPath))" | Set-Content -LiteralPath $checksumPath -Encoding ascii

    Write-Host ""
    Write-Host "Unsigned portable release created:"
    Write-Host "  $zipPath"
    Write-Host "  $checksumPath"
    Write-Host "SHA-256: $hash"
    Write-Host "Windows may display an Unknown publisher warning because the executable is intentionally unsigned."
}
finally {
    Pop-Location
}
