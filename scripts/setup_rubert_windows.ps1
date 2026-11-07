param([string]$Root = 'D:\RuBERT')

# Isolated project runtime; no system PATH/driver/launcher changes.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
if (-not [IO.Path]::IsPathRooted($Root)) { throw 'Root must be an absolute path.' }
$marker = Join-Path $Root '.parsevk-training-root'
if ((Test-Path $Root) -and -not (Test-Path $marker)) {
    throw 'Existing unmarked directory: choose an empty/new project directory; no overwrite.'
}
New-Item -ItemType Directory -Force -Path $Root | Out-Null
if (-not (Test-Path $marker)) { Set-Content -Path $marker -Value 'ParseVK isolated training runtime v1' -Encoding ASCII }
foreach ($sub in @('downloads','logs','runtime','cache','outputs')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $Root $sub) | Out-Null
}

$version = '3.13.17'
$runtime = Join-Path $Root 'runtime\Python313'
$python = Join-Path $runtime 'python.exe'
if (-not (Test-Path $python)) {
    if (Test-Path $runtime) { throw 'Partial runtime exists; inspect before retrying installation.' }
    $installer = Join-Path $Root "downloads\python-$version-amd64.exe"
    $url = "https://www.python.org/ftp/python/$version/python-$version-amd64.exe"
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $installer -TimeoutSec 120
    $signature = Get-AuthenticodeSignature $installer
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
        throw 'Python installer signature is not valid for Python Software Foundation.'
    }
    $hash = (Get-FileHash $installer -Algorithm SHA256).Hash
    [ordered]@{url=$url; sha256=$hash; signature=$signature.Status.ToString(); signer=$signature.SignerCertificate.Subject} |
        ConvertTo-Json | Set-Content (Join-Path $Root 'logs\python_installer.json') -Encoding UTF8
    $arguments = @('/quiet','InstallAllUsers=0',"TargetDir=`"$runtime`"",'PrependPath=0',
        'Include_launcher=0','AssociateFiles=0','Shortcuts=0','Include_test=0','Include_doc=0',
        '/log',"`"$(Join-Path $Root 'logs\python_install.log')`"")
    $process = Start-Process -FilePath $installer -ArgumentList $arguments -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Python installer failed: $($process.ExitCode). No reboot or retry performed." }
}
& $python -c 'import sys; assert sys.version_info[:2] == (3,13); print(sys.version)'
if ($LASTEXITCODE -ne 0) { throw 'Unexpected Python runtime.' }
$venv = Join-Path $Root '.venv-rubert'
$venvPython = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    if (Test-Path $venv) { throw 'Partial virtual environment exists; inspect before retrying.' }
    & $python -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'venv creation failed.' }
}

# --isolated ignores user pip configuration; no private index or token is needed.
# torchvision/torchaudio/TensorFlow/CUDA Toolkit are not required for text BERT.
& $venvPython -m pip --isolated --log (Join-Path $Root 'logs\pip_torch.log') install --no-cache-dir --only-binary=:all: --index-url https://download.pytorch.org/whl/cu126 'torch==2.7.1'
if ($LASTEXITCODE -ne 0) { throw 'PyTorch installation failed; no provider/version fallback.' }
& $venvPython -m pip --isolated --log (Join-Path $Root 'logs\pip_nlp.log') install --no-cache-dir --only-binary=:all: --index-url https://pypi.org/simple 'transformers==4.57.1' 'scikit-learn==1.7.2' 'numpy==2.2.6'
if ($LASTEXITCODE -ne 0) { throw 'NLP dependencies installation failed.' }
& $venvPython -m pip --isolated check
if ($LASTEXITCODE -ne 0) { throw 'Dependency conflicts found.' }
& $venvPython -m pip --isolated freeze | Set-Content (Join-Path $Root 'logs\requirements-resolved.txt') -Encoding UTF8
if ($LASTEXITCODE -ne 0) { throw 'Could not capture resolved dependencies.' }
Write-Output "Environment prepared: $venvPython"
Write-Output 'CUDA smoke-test is a separate step. No corpus or model weights downloaded; no training started.'
