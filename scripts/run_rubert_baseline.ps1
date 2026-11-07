param(
    [ValidateSet('benchmark','train')][string]$Mode = 'benchmark',
    [ValidateSet('A','B')][string]$Task = 'A',
    [string]$Project = 'D:\RuBERT\project_baseline_v1',
    [string]$RuntimeRoot = 'D:\RuBERT',
    [int]$Epochs = 3,
    [ValidateSet(128,256,512)][int]$MaxLength = 512
)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:HF_HOME = Join-Path $RuntimeRoot 'cache\huggingface'
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = '1'
$python = Join-Path $RuntimeRoot '.venv-rubert\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'Training environment not found.' }
if (-not (Test-Path (Join-Path $Project 'dataset\manifest.json'))) { throw 'Frozen dataset not found.' }
if ($Epochs -lt 1) { throw 'Epochs must be positive.' }
$stamp = [DateTime]::UtcNow.ToString('yyyyMMdd_HHmmss_fffffff')
$output = Join-Path $RuntimeRoot "outputs\${Mode}_${Task}_$stamp"
Push-Location $Project
try {
    # Foreground: keep this session alive until completion. There is no automatic
    # task scheduling, resume, paid service, or CPU/configuration fallback.
    & $python -m src.rubert_training $Mode --dataset dataset --task $Task --output $output --max-length $MaxLength --batch-size 2 --accumulation 8 --epochs $Epochs
    if ($LASTEXITCODE -ne 0) { throw "Run failed; inspect $output before choosing a new run." }
} finally {
    Pop-Location
}
