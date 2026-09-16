$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$wslRoot = wsl -d Ubuntu -- wslpath -a "$repoRoot"

wsl -d Ubuntu -- bash -lc '
    cd "$1"
    runtime=/home/adithyarama/.venvs/3d_hyperspec_ai/bin/python
    if [ ! -x "$runtime" ]; then
        echo "Missing showcase runtime: $runtime" >&2
        echo "Create it with Python 3 and install spectral, matplotlib, opencv-python-headless, scikit-image, and scikit-learn." >&2
        exit 1
    fi
    "$runtime" scripts/generate_showcase.py \
        --data-dir data/20260828 \
        --output-dir results/20260828_showcase \
        --stride 4
' bash $wslRoot

if ($LASTEXITCODE -ne 0) {
    throw "Showcase generation failed with exit code $LASTEXITCODE"
}

$gallery = Join-Path $repoRoot "results\20260828_showcase\index.html"
Write-Output "Showcase ready: $gallery"
