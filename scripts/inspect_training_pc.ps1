# Read-only inventory for the Windows RuBERT training environment.
# Run in Windows PowerShell 5.1 or PowerShell 7. No installs or configuration changes.
# JSON is printed to stdout; redirect it to a private file if needed.
$ErrorActionPreference = 'Stop'
$report = [ordered]@{
    collected_utc = [DateTime]::UtcNow.ToString('o')
    powershell = $PSVersionTable.PSVersion.ToString()
    os = $null
    cpu = @()
    ram_gib = $null
    disks = @()
    display_adapters = @()
    nvidia_smi = $null
    python_launcher = $null
    warnings = @()
}

try {
    $os = Get-CimInstance Win32_OperatingSystem
    $report.os = [ordered]@{caption=$os.Caption; version=$os.Version; architecture=$os.OSArchitecture}
    $report.ram_gib = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
    $report.cpu = @(Get-CimInstance Win32_Processor | ForEach-Object {
        [ordered]@{name=$_.Name; cores=$_.NumberOfCores; logical_processors=$_.NumberOfLogicalProcessors}
    })
    $report.disks = @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | ForEach-Object {
        [ordered]@{drive=$_.DeviceID; size_gib=[math]::Round($_.Size / 1GB,2); free_gib=[math]::Round($_.FreeSpace / 1GB,2)}
    })
    $report.display_adapters = @(Get-CimInstance Win32_VideoController | ForEach-Object {
        [ordered]@{name=$_.Name; driver_version=$_.DriverVersion}
    })
} catch {
    $report.warnings += 'CIM inventory incomplete; check Windows permissions and CIM availability.'
}

$smi = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
if ($null -ne $smi) {
    $smiPath = $smi.Source
} elseif (Test-Path "$env:SystemRoot\System32\nvidia-smi.exe") {
    $smiPath = "$env:SystemRoot\System32\nvidia-smi.exe"
} elseif (Test-Path "$env:ProgramFiles\NVIDIA Corporation\NVSMI\nvidia-smi.exe") {
    $smiPath = "$env:ProgramFiles\NVIDIA Corporation\NVSMI\nvidia-smi.exe"
} else {
    $smiPath = $null
}
if ($null -ne $smiPath) {
    try {
        $rows = @(& $smiPath '--query-gpu=name,memory.total,memory.free,driver_version' '--format=csv,noheader,nounits' 2>&1 | ForEach-Object { $_.ToString() })
        if ($LASTEXITCODE -ne 0) { throw 'nvidia-smi failed' }
        $report.nvidia_smi = [ordered]@{columns=@('name','memory_total_mib','memory_free_mib','driver_version'); rows=$rows}
    } catch {
        $report.warnings += 'nvidia-smi was found but could not query the GPU.'
    }
} else {
    $report.warnings += 'nvidia-smi not found. This does not independently prove that the PC has no NVIDIA GPU.'
}

$launcher = Get-Command py.exe -ErrorAction SilentlyContinue
if ($null -ne $launcher) {
    try {
        $listing = @(& $launcher.Source '-0p' 2>&1 | ForEach-Object { $_.ToString() })
        if ($LASTEXITCODE -ne 0) { throw 'Python launcher failed' }
        $report.python_launcher = $listing
    } catch {
        $report.warnings += 'Python launcher inventory unavailable.'
    }
} else {
    $report.warnings += 'py.exe launcher not found; Python may still be installed by another method.'
}

$report | ConvertTo-Json -Depth 6
