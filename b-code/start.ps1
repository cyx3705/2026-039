$ErrorActionPreference = 'Stop'
$rootDir = $PSScriptRoot
$serviceRoot = 'F:\LinuxModuleServices'
$stateDir = Join-Path $serviceRoot 'b-code'
$modelRoot = 'F:\Models\Ollama'
$wslService = '/mnt/f/LinuxModuleServices/scripts/wsl-model-service.sh'
$manifestPath = Join-Path $modelRoot 'manifests\registry.ollama.ai\library\qwen3\8b'
if (-not (Test-Path -LiteralPath $manifestPath) -or -not (Test-Path -LiteralPath 'F:\LinuxModuleServices\scripts\wsl-model-service.sh')) {
    throw 'Prepare models under F:\Models and the WSL service under F:\LinuxModuleServices first. No fallback to C:.'
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$digest = ($manifest.layers | Where-Object mediaType -eq 'application/vnd.ollama.image.model').digest.Replace(':','-')
$modelPath = Join-Path $modelRoot "blobs\$digest"
if (-not (Test-Path -LiteralPath $modelPath)) { throw 'Model file missing on F:.' }

function Test-Endpoint($url) {
    try { $null = Invoke-RestMethod -Uri $url -TimeoutSec 2 -NoProxy; return $true }
    catch { return $false }
}

# Do not move live run files or interrupt an experiment.
if (Test-Endpoint 'http://127.0.0.1:18766/state') {
    $runState = Invoke-RestMethod 'http://127.0.0.1:18766/state' -NoProxy
    if ($runState.status -eq 'running') { throw 'Experiment running; wait until idle before launching/reconfiguring services.' }
}
foreach ($folder in @($stateDir, "$stateDir\logs", "$stateDir\temp", "$stateDir\cache", "$stateDir\runs")) {
    $null = New-Item -ItemType Directory -Path $folder -Force
}

function Stop-ManagedService($kind, $expectedName) {
    $pidFile = Join-Path $stateDir "$kind.pid"
    if (-not (Test-Path -LiteralPath $pidFile)) { $pidFile = Join-Path $rootDir "$kind.pid" }
    if (Test-Path -LiteralPath $pidFile) {
        $owned = Get-Process -Id ([int](Get-Content -LiteralPath $pidFile)) -ErrorAction SilentlyContinue
        if ($owned) {
            if ($owned.ProcessName -ne $expectedName) { throw "Saved $kind PID belongs to a different process" }
            Stop-Process -Id $owned.Id
        }
    }
}

# Preserve source-relative URLs and CLI paths; new run writes go to F:.
$runsPath = Join-Path $rootDir 'runs'
$targetRuns = Join-Path $stateDir 'runs'
if (Test-Path -LiteralPath $runsPath) {
    $runsItem = Get-Item -LiteralPath $runsPath
    if ($runsItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        if ([IO.Path]::GetFullPath([string]$runsItem.Target).TrimEnd('\') -ne $targetRuns.TrimEnd('\')) {
            throw 'Existing runs junction points to an unexpected directory'
        }
    } else {
        Stop-ManagedService 'viewer' 'python'
        & robocopy $runsPath $targetRuns /E /COPY:DAT /DCOPY:DAT /R:1 /W:1 /NFL /NDL /NJH /NJS /NP
        if ($LASTEXITCODE -ge 8) { throw 'Run archive copy failed; originals preserved' }
        $backupPath = Join-Path $rootDir ('runs-before-f-drive-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
        $sourceResolved = (Resolve-Path -LiteralPath $runsPath).Path
        $backupResolved = [IO.Path]::GetFullPath($backupPath)
        if (-not $sourceResolved.StartsWith($rootDir + '\', [StringComparison]::OrdinalIgnoreCase) -or
            -not $backupResolved.StartsWith($rootDir + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Archive migration paths escaped the project directory'
        }
        Move-Item -LiteralPath $runsPath -Destination $backupPath
        $null = New-Item -ItemType Junction -Path $runsPath -Value $targetRuns
    }
} else {
    $null = New-Item -ItemType Junction -Path $runsPath -Value $targetRuns
}

$env:TEMP = Join-Path $stateDir 'temp'
$env:TMP = $env:TEMP
$env:CUDA_CACHE_PATH = Join-Path $stateDir 'cache\cuda'
$env:OLLAMA_MODELS = $modelRoot
$env:HF_HOME = 'F:\Models\HuggingFace'
$env:MODELSCOPE_CACHE = 'F:\Models\ModelScope\hub'
$env:TORCH_HOME = Join-Path $stateDir 'cache\torch'
$env:XDG_CACHE_HOME = Join-Path $stateDir 'cache'
$env:PYTHONPYCACHEPREFIX = Join-Path $stateDir 'cache\pycache'
$env:GGML_BACKEND_PATH = $null

if (Test-Endpoint 'http://127.0.0.1:18765/props') {
    $props = Invoke-RestMethod 'http://127.0.0.1:18765/props' -NoProxy
    if ($props.default_generation_settings.n_ctx -ne 32768) {
        wsl -d Ubuntu -e bash $wslService stop-experiment
        Start-Sleep -Seconds 1
    }
}
if (-not (Test-Endpoint 'http://127.0.0.1:18765/props')) {
    wsl -d Ubuntu -e bash $wslService start-experiment
    if ($LASTEXITCODE -ne 0) { throw 'WSL model service failed; see F:\LinuxModuleServices\linux-logs\experiment-llama.log' }
    $ready = $false
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        if (Test-Endpoint 'http://127.0.0.1:18765/props') { $ready = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'Model loading timed out; see F:\LinuxModuleServices\linux-logs\experiment-llama.log' }
}
Set-Content -LiteralPath (Join-Path $stateDir 'model.pid') -Value 'wsl' -Encoding ascii
if (-not (Test-Endpoint 'http://127.0.0.1:18766/')) {
    $pythonPath = (Get-Command python).Source
    $viewerProcess = Start-Process -FilePath $pythonPath -ArgumentList @(('"' + (Join-Path $rootDir 'server.py') + '"')) -WorkingDirectory $stateDir -WindowStyle Hidden -RedirectStandardOutput (Join-Path $stateDir 'logs\viewer.stdout.log') -RedirectStandardError (Join-Path $stateDir 'logs\viewer.stderr.log') -PassThru
    $viewerProcess.Id | Set-Content (Join-Path $stateDir 'viewer.pid')
}
Write-Host 'Viewer: http://127.0.0.1:18766'
Write-Host 'Model:  http://127.0.0.1:18765'
Write-Host "Runtime data: $stateDir"
