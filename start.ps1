#requires -Version 5.1
[CmdletBinding()]
param([switch]$CheckOnly, [switch]$DoubleClick, [switch]$CollectBrowser)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
# UTF-8 is explicit for Python and redirected console output on Windows.
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONDONTWRITEBYTECODE = '1'
$AppMutex = $null
$CollectorMutex = $null
$HasAppLock = $false
$HasCollectorLock = $false
$ExitCode = 0

function Try-LauncherLock($Mutex) {
    try { return $Mutex.WaitOne(0) }
    catch [System.Threading.AbandonedMutexException] { return $true }
}

function Edit-LocalSettings {
    Write-Host '請設定自訂 WEB_USERNAME 與至少 12 字元的 WEB_PASSWORD。不要貼出密碼或 API Key。'
    & notepad.exe (Join-Path $PSScriptRoot '.env')
    [void](Read-Host '請在記事本儲存 .env，完成後回到此視窗按 Enter')
}

function Get-DependencyStamp([string[]]$Paths) {
    # Direct .NET hashing also works when PowerShell 5.1 inherits PS7's module path.
    $Digests = foreach ($Path in $Paths) {
        $FilePath = $Path
        if (-not [IO.Path]::IsPathRooted($FilePath)) { $FilePath = Join-Path $PSScriptRoot $FilePath }
        $Stream = [IO.File]::OpenRead($FilePath)
        $Hasher = [Security.Cryptography.SHA256]::Create()
        try { [BitConverter]::ToString($Hasher.ComputeHash($Stream)).Replace('-', '') }
        finally { $Hasher.Dispose(); $Stream.Dispose() }
    }
    return ($Digests -join ':')
}

function Test-Stamp([string]$Path, [string]$Value) {
    return (Test-Path -LiteralPath $Path -PathType Leaf) -and ((Get-Content -LiteralPath $Path -Raw -Encoding UTF8).Trim() -eq $Value)
}

Push-Location $PSScriptRoot
try {
    if ($CheckOnly -and ($DoubleClick -or $CollectBrowser)) { throw '-CheckOnly 不可與其他啟動模式合用。' }
    # Use Python only after PowerShell has permitted this file. Never alter policy.
    $Python = $null
    $PythonArgs = @()
    foreach ($Candidate in @('python.exe', 'python3.exe', 'py.exe')) {
        $Command = Get-Command $Candidate -ErrorAction SilentlyContinue
        if (-not $Command) { continue }
        $CandidateArgs = @()
        if ($Candidate -eq 'py.exe') { $CandidateArgs = @('-3') }
        try {
            & $Command.Source @CandidateArgs -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>$null
        } catch { continue }
        if ($LASTEXITCODE -eq 0) {
            $Python = $Command.Source
            $PythonArgs = $CandidateArgs
            break
        }
    }
    if (-not $Python) { throw '請先安裝 Python 3.11 以上版本，並將 Python 加入 PATH，再重新雙擊。' }
    $VenvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    $Helper = Join-Path $PSScriptRoot 'scripts\windows_launch.py'

    if (-not $CheckOnly) {
        # Named kernel mutexes disappear when their owner exits, even after a crash.
        # The app lock covers preparation AND app lifetime. The collector lock
        # protects its lifetime and excludes dependency updates during collection.
        $Hash = [System.Security.Cryptography.SHA256]::Create()
        try {
            $Identity = [System.IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\').ToUpperInvariant()
            $Digest = [BitConverter]::ToString($Hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($Identity))).Replace('-', '')
        } finally { $Hash.Dispose() }
        $AppMutex = New-Object System.Threading.Mutex($false, "Local\ShopeeTw-$Digest-app")
        $CollectorMutex = New-Object System.Threading.Mutex($false, "Local\ShopeeTw-$Digest-collector")
        if ($CollectBrowser) {
            $HasCollectorLock = Try-LauncherLock $CollectorMutex
            if (-not $HasCollectorLock) { throw '已有瀏覽實驗或環境準備執行中，請查看原視窗，不會重複開啟。' }
            $BrowserReady = $false
            if (Test-Path -LiteralPath $VenvPython -PathType Leaf) {
                & $VenvPython -c 'import importlib.util, sys; sys.exit(0 if sys.version_info >= (3, 11) and all(importlib.util.find_spec(name) is not None for name in (''dotenv'', ''pydantic'', ''playwright'')) else 1)' 2>$null
                $BrowserReady = ($LASTEXITCODE -eq 0)
            }
            if (-not $BrowserReady) {
                $HasAppLock = Try-LauncherLock $AppMutex
                if (-not $HasAppLock) { throw '首次安裝選用瀏覽依賴前，請先在主程式視窗按 Ctrl+C 停止服務，再重新雙擊。安裝完成後可與主程式同時使用。' }
                # Older/manual servers do not hold our mutex. Do not update their packages.
                $ProbeArgs = @('existing')
                if (-not (Test-Path -LiteralPath '.env' -PathType Leaf)) { $ProbeArgs += @('--port', '8000') }
                & $Python @PythonArgs $Helper @ProbeArgs
                if ($LASTEXITCODE -ne 3) { throw '安裝選用依賴前，請先停止此連接埠的既有服務；不會修改執行中的環境。' }
                Write-Host '此功能是選用實驗，不會自動登入、避開驗證或安裝瀏覽器。請先準備 browser-request.json。'
                Write-Host '選用依賴清單：requirements-browser.txt。只有輸入 yes 才會安裝。'
                $Answer = Read-Host '是否在本專案安裝 requirements-browser.txt 的選用依賴？輸入 yes 才會安裝'
                if ($Answer.Trim().ToLowerInvariant() -ne 'yes') { Write-Host '已取消，未安裝依賴，未開啟瀏覽器。'; return }
                if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
                    & $Python @PythonArgs -m venv .venv
                    if ($LASTEXITCODE -ne 0) { throw '建立 Python 虛擬環境失敗。' }
                }
                & $VenvPython -m pip install -r requirements-browser.txt
                if ($LASTEXITCODE -ne 0) { throw '選用瀏覽依賴安裝失敗；未開啟瀏覽器。' }
                $RuntimeStamp = Get-DependencyStamp @('requirements-runtime.txt')
                Set-Content -LiteralPath '.venv\.runtime-install.sha256' -Value $RuntimeStamp -Encoding UTF8
                $AppMutex.ReleaseMutex()
                $HasAppLock = $false
            }
            & $VenvPython $Helper collect
            if ($LASTEXITCODE -ne 0) { throw '本批瀏覽實驗未完成，請查看上方停止原因與結果檔。' }
            return
        }
        $HasAppLock = Try-LauncherLock $AppMutex
        if (-not $HasAppLock) {
            if (Test-Path -LiteralPath '.env' -PathType Leaf) {
                & $Python @PythonArgs $Helper existing --open-browser
                if ($LASTEXITCODE -eq 0) { return }
            }
            Write-Host '原啟動視窗正在準備環境或啟動服務，請保留原視窗並等待。不會重複安裝或啟動。'
            return
        }
        if (-not (Test-Path -LiteralPath '.env' -PathType Leaf)) {
            if (-not $DoubleClick) { throw '請先複製 .env.example 為 .env，再設定自訂登入帳密。' }
            # Atomic create-only copy: never replace the user's existing settings.
            [System.IO.File]::Copy((Join-Path $PSScriptRoot '.env.example'), (Join-Path $PSScriptRoot '.env'), $false)
            Write-Host '已建立新的 .env；既有設定與資料不會覆寫。'
            Edit-LocalSettings
        }
        & $Python @PythonArgs $Helper existing --open-browser
        if ($LASTEXITCODE -eq 0) { return }
        if ($LASTEXITCODE -ne 3) { throw '本機連接埠或設定檢查未通過，請查看上方訊息。' }
    }

    $Node = Get-Command node.exe -ErrorAction SilentlyContinue
    $Npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $Node -or -not $Npm) { throw '請先安裝 Node.js 22.12 以上版本（包含 npm），再重新開啟啟動視窗。' }
    $NodeVersionText = & $Node.Source --version
    if ($LASTEXITCODE -ne 0) { throw 'Node.js 版本檢查失敗。' }
    $NodeVersion = [version]($NodeVersionText.Trim().TrimStart('v'))
    if ($NodeVersion -lt [version]'22.12.0') { throw '需要 Node.js 22.12 以上版本。' }
    if (-not (Test-Path -LiteralPath '.env' -PathType Leaf)) {
        throw '請先複製 .env.example 為 .env，再編輯 WEB_USERNAME 與 WEB_PASSWORD。'
    }
    if ($CheckOnly) {
        if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) { throw '尚未建立 .venv。請先執行 .\start.ps1 安裝依賴；本次檢查沒有變更任何檔案。' }
        & $VenvPython scripts/check_config.py
        if ($LASTEXITCODE -ne 0) { throw '應用程式設定檢查失敗。' }
        if (-not (Test-Path -LiteralPath 'dist\index.html' -PathType Leaf)) { throw '前端尚未建置。請執行 .\start.ps1。' }
        Write-Host '環境與設定檢查通過；未啟動伺服器，也未連線至外部服務。'
        return
    }

    $RuntimeStamp = Get-DependencyStamp @('requirements-runtime.txt')
    $FrontendStamp = Get-DependencyStamp @('web-ui\package.json', 'web-ui\package-lock.json')
    # Include frontend sources so extracting an updated ZIP triggers a fresh build.
    $FrontendRoots = @('web-ui\src')
    if (Test-Path -LiteralPath 'web-ui\public' -PathType Container) { $FrontendRoots += 'web-ui\public' }
    $FrontendSources = @(Get-ChildItem -LiteralPath $FrontendRoots -Recurse -File | Sort-Object FullName | ForEach-Object { $_.FullName })
    $FrontendSources += @(Get-ChildItem -Path 'web-ui\vite.config.*', 'web-ui\*.config.cjs', 'web-ui\tsconfig*.json', 'web-ui\index.html' -File | Sort-Object FullName | ForEach-Object { $_.FullName })
    $FrontendStamp += ':' + (Get-DependencyStamp $FrontendSources)
    $NeedRuntime = (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) -or (-not (Test-Stamp '.venv\.runtime-install.sha256' $RuntimeStamp))
    $NeedFrontend = (-not (Test-Path -LiteralPath 'dist\index.html' -PathType Leaf)) -or (-not (Test-Stamp '.venv\.frontend-build.sha256' $FrontendStamp))
    if ($NeedRuntime -or $NeedFrontend) {
        $HasCollectorLock = Try-LauncherLock $CollectorMutex
        if (-not $HasCollectorLock) { throw '瀏覽實驗正在執行，無法同時更新環境。請先完成或取消該批，再重新啟動。' }
    }
    if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
        & $Python @PythonArgs -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw '建立 Python 虛擬環境失敗。' }
    }
    & $VenvPython -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'
    if ($LASTEXITCODE -ne 0) { throw '既有 .venv 需要 Python 3.11 以上版本。請在新的解壓縮資料夾建立環境。' }
    if ($NeedRuntime) {
        & $VenvPython -m pip install -r requirements-runtime.txt
        if ($LASTEXITCODE -ne 0) { throw 'Python 依賴安裝失敗。' }
        Set-Content -LiteralPath '.venv\.runtime-install.sha256' -Value $RuntimeStamp -Encoding UTF8
    }
    $ErrorActionPreference = 'Continue'
    & $VenvPython scripts/check_config.py
    $ConfigResult = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($ConfigResult -ne 0 -and $DoubleClick) {
        $Answer = Read-Host '登入設定尚未完成。是否以記事本編輯 .env？輸入 yes 開啟'
        if ($Answer.Trim().ToLowerInvariant() -eq 'yes') { Edit-LocalSettings }
        $ErrorActionPreference = 'Continue'
        & $VenvPython scripts/check_config.py
        $ConfigResult = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
    }
    if ($ConfigResult -ne 0) { throw '應用程式設定檢查失敗。' }
    $Port = & $VenvPython scripts/check_config.py --port
    if ($LASTEXITCODE -ne 0) { throw '連接埠設定檢查失敗。' }
    if ($NeedFrontend) {
        Push-Location web-ui
        try {
            & $Npm.Source ci
            if ($LASTEXITCODE -ne 0) { throw '前端依賴安裝失敗。' }
            & $Npm.Source run build
            if ($LASTEXITCODE -ne 0) { throw '前端建置失敗。' }
        } finally { Pop-Location }
        Set-Content -LiteralPath '.venv\.frontend-build.sha256' -Value $FrontendStamp -Encoding UTF8
    }
    if ($HasCollectorLock) { $CollectorMutex.ReleaseMutex(); $HasCollectorLock = $false }
    # Supervisor binds --host 127.0.0.1, waits for matching /health, then opens once.
    & $VenvPython $Helper serve --port $Port --open-browser
    if ($LASTEXITCODE -ne 0) { throw '伺服器已停止，請查看上方錯誤訊息。' }
} catch {
    Write-Host ("啟動未完成：" + $_.Exception.Message) -ForegroundColor Red
    $ExitCode = 1
} finally {
    if ($HasCollectorLock) { $CollectorMutex.ReleaseMutex() }
    if ($HasAppLock) { $AppMutex.ReleaseMutex() }
    if ($CollectorMutex) { $CollectorMutex.Dispose() }
    if ($AppMutex) { $AppMutex.Dispose() }
    Pop-Location
}
if ($ExitCode -ne 0) { exit $ExitCode }
