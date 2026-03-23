param(
    [ValidateSet("build", "install", "verify", "all")]
    [string]$Action = "all",
    [string]$ManifestPath = "rust/weighted_core_pyo3/Cargo.toml",
    [string]$WheelDir = "dist/wheels"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-CommandExists {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )
    if (Get-Command $Name -ErrorAction SilentlyContinue) { return }
    $cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
    $exePath = Join-Path $cargoBin ("{0}.exe" -f $Name)
    if (Test-Path $exePath) {
        if ($env:PATH -notlike "*$cargoBin*") {
            $env:PATH = "$cargoBin;$env:PATH"
        }
        return
    }
    throw "必要なコマンドが見つかりません: $Name"
}

function Resolve-LatestWheel {
    param(
        [Parameter(Mandatory = $true)]
        [string]$DirPath
    )
    $dir = Resolve-Path $DirPath
    $wheel = Get-ChildItem -Path $dir -Filter "weighted_core_pyo3-*.whl" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $wheel) {
        throw "wheel が見つかりません: $dir"
    }
    return $wheel.FullName
}

function Build-Wheel {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CargoManifestPath,
        [Parameter(Mandatory = $true)]
        [string]$OutDir
    )
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
    Assert-CommandExists -Name "cargo"
    uv run maturin build `
        --release `
        --manifest-path $CargoManifestPath `
        --out $OutDir
    if ($LASTEXITCODE -ne 0) {
        throw "maturin build に失敗しました（exit=$LASTEXITCODE）。"
    }
    return Resolve-LatestWheel -DirPath $OutDir
}

function Install-Wheel {
    param(
        [Parameter(Mandatory = $true)]
        [string]$WheelPath
    )
    uv pip install --python .venv\Scripts\python.exe --reinstall $WheelPath
    if ($LASTEXITCODE -ne 0) {
        throw "wheel install に失敗しました（exit=$LASTEXITCODE）。"
    }
}

function Verify-Import {
    uv run python -c "import numpy as np, weighted_core_pyo3 as m; f=np.ones((1,2,2),dtype=float); w=np.ones((2,2),dtype=float); out=m.compute_weighted_core(f,w,-9999.0); assert abs(out['weighted_sum_mm'][0]-4.0)<1e-9; print('weighted_core_pyo3 import/compute: OK')"
    if ($LASTEXITCODE -ne 0) {
        throw "import/compute 検証に失敗しました（exit=$LASTEXITCODE）。"
    }
}

if ($Action -eq "build") {
    $wheel = Build-Wheel -CargoManifestPath $ManifestPath -OutDir $WheelDir
    Write-Host "built: $wheel"
    exit 0
}

if ($Action -eq "install") {
    $wheel = Resolve-LatestWheel -DirPath $WheelDir
    Install-Wheel -WheelPath $wheel
    Write-Host "installed: $wheel"
    exit 0
}

if ($Action -eq "verify") {
    Verify-Import
    exit 0
}

$built = Build-Wheel -CargoManifestPath $ManifestPath -OutDir $WheelDir
Install-Wheel -WheelPath $built
Verify-Import
Write-Host "done: $built"
