#requires -Version 5.1
[CmdletBinding()]
param([switch]$CheckOnly)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Push-Location $PSScriptRoot
try {
    # Do not activate the venv or change PowerShell execution/security settings.
    # Prefer a modern Python on PATH. A legacy py launcher may only know Python 2.7.
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
    if (-not $Python) { throw '請先安裝 Python 3.11 以上版本，並將 Python 加入 PATH。' }

    $Node = Get-Command node.exe -ErrorAction SilentlyContinue
    $Npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $Node -or -not $Npm) { throw '請先安裝 Node.js 22.12 以上版本（包含 npm），再重新開啟 PowerShell。' }
    $NodeVersionText = & $Node.Source --version
    if ($LASTEXITCODE -ne 0) { throw 'Node.js 版本檢查失敗。' }
    $NodeVersion = [version]($NodeVersionText.Trim().TrimStart('v'))
    if ($NodeVersion -lt [version]'22.12.0') { throw '需要 Node.js 22.12 以上版本。' }
    if (-not (Test-Path -LiteralPath '.env' -PathType Leaf)) {
        throw '請先 Copy-Item .env.example .env，再編輯 WEB_USERNAME 與 WEB_PASSWORD。'
    }

    $VenvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if ($CheckOnly) {
        if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) { throw '尚未建立 .venv。請先執行 .\start.ps1 安裝依賴；本次檢查沒有變更任何檔案。' }
        & $VenvPython scripts/check_config.py
        if ($LASTEXITCODE -ne 0) { throw '應用程式設定檢查失敗。' }
        if (-not (Test-Path -LiteralPath 'dist\index.html' -PathType Leaf)) { throw '前端尚未建置。請執行 .\start.ps1。' }
        Write-Host '環境與設定檢查通過；未啟動伺服器，也未連線至外部服務。'
        return
    }

    if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
        & $Python @PythonArgs -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw '建立 Python 虛擬環境失敗。' }
    }
    & $VenvPython -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'
    if ($LASTEXITCODE -ne 0) { throw '既有 .venv 需要 Python 3.11 以上版本。請在新的解壓縮資料夾建立環境。' }
    & $VenvPython -m pip install -r requirements-runtime.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python 依賴安裝失敗。' }
    & $VenvPython scripts/check_config.py
    if ($LASTEXITCODE -ne 0) { throw '應用程式設定檢查失敗。' }
    $Port = & $VenvPython scripts/check_config.py --port
    if ($LASTEXITCODE -ne 0) { throw '連接埠設定檢查失敗。' }

    Push-Location web-ui
    try {
        & $Npm.Source ci
        if ($LASTEXITCODE -ne 0) { throw '前端依賴安裝失敗。' }
        & $Npm.Source run build
        if ($LASTEXITCODE -ne 0) { throw '前端建置失敗。' }
    } finally { Pop-Location }

    Write-Host "請開啟 http://127.0.0.1:$Port ，使用自訂帳號登入。按 Ctrl+C 停止。"
    & $VenvPython -m uvicorn src.app:app --host 127.0.0.1 --port $Port --env-file .env
    if ($LASTEXITCODE -ne 0) { throw '伺服器已停止，請查看上方錯誤訊息。' }
} finally {
    Pop-Location
}
