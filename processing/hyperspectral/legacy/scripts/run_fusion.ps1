$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$rgbdDataset = "C:\Personal\My_DEGREE's\Master_of_Computing_(Advanced)\Australian_National_University\Technical Team Project - COMP8715\PhenoFusion3D\data\main\test_plant_20260828120800_best_lighting"

if (-not (Test-Path -LiteralPath $rgbdDataset)) {
    throw "RGB-D dataset not found: $rgbdDataset"
}

# Stage the presentation-sized RGB-D/ICP evidence beside the hyperspectral report.
$rgbdBundle = Join-Path $repoRoot "results\20260828_showcase\rgbd_icp"
New-Item -ItemType Directory -Force -Path $rgbdBundle, (Join-Path $rgbdBundle "plants"), (Join-Path $rgbdBundle "validation") | Out-Null
Copy-Item -LiteralPath (Join-Path $rgbdDataset "merge_simple_full_step10\reconstruction_summary.json") -Destination (Join-Path $rgbdBundle "reconstruction_summary.json") -Force
Copy-Item -LiteralPath (Join-Path $rgbdDataset "merge_simple_full_step10\diagnostics\scene_geometry_diagnostics.json") -Destination (Join-Path $rgbdBundle "scene_geometry_diagnostics.json") -Force
Copy-Item -LiteralPath (Join-Path $rgbdDataset "merge_simple_full_step10\diagnostics\scene_top_side_preview.png") -Destination (Join-Path $rgbdBundle "scene_top_side_preview.png") -Force
Copy-Item -LiteralPath (Join-Path $rgbdDataset "merge_simple_full_step10\diagnostics\scene_preview_sampled.ply") -Destination (Join-Path $rgbdBundle "scene_preview_sampled.ply") -Force
Copy-Item -LiteralPath (Join-Path $rgbdDataset "validation\software_traits\software_traits.csv") -Destination (Join-Path $rgbdBundle "software_traits.csv") -Force
Copy-Item -LiteralPath (Join-Path $rgbdDataset "validation\software_traits\software_traits.json") -Destination (Join-Path $rgbdBundle "software_traits.json") -Force
Get-ChildItem -LiteralPath (Join-Path $rgbdDataset "validation\report") -File | Copy-Item -Destination (Join-Path $rgbdBundle "validation") -Force
& (Join-Path $PSScriptRoot "stage_validation_assets.ps1") -RgbdDataset $rgbdDataset -RgbdBundle $rgbdBundle

foreach ($entry in @(
    @{ Id = "plant_1"; Key = "succulent_jade" },
    @{ Id = "plant_2"; Key = "coleus" },
    @{ Id = "plant_3"; Key = "fuzzy_kalanchoe" }
)) {
    $plantOutput = Join-Path $rgbdBundle ("plants\" + $entry.Key)
    New-Item -ItemType Directory -Force -Path $plantOutput | Out-Null
    foreach ($name in @("plant_overlay.png", "leaf_segments.png", "plant_mask.png", "traits.json", "visible_leaves.json", "specimen_pointcloud.ply")) {
        Copy-Item -LiteralPath (Join-Path $rgbdDataset ("validation\software_traits\" + $entry.Id + "\" + $name)) -Destination (Join-Path $plantOutput $name) -Force
    }
}

$wslRoot = wsl -d Ubuntu -- wslpath -a "$repoRoot"
$wslRgbd = wsl -d Ubuntu -- wslpath -a "$rgbdDataset"
$python = "/home/adithyarama/.venvs/3d_hyperspec_ai/bin/python"
$fusionCommand = "cd `"$wslRoot`" && " +
    "$python scripts/fuse_rgbd_hyperspectral.py --rgbd-dir `"$wslRgbd`" --plants coleus fuzzy_kalanchoe succulent_jade && " +
    "$python scripts/recover_global_placement.py --dataset `"$wslRgbd`" && " +
    "$python scripts/build_interactive_viewer_assets.py && " +
    "$python scripts/generate_showcase.py --output-dir results/20260828_showcase --report-only && " +
    "$python scripts/validate_fusion.py"

wsl -d Ubuntu -- bash -lc $fusionCommand
if ($LASTEXITCODE -ne 0) {
    throw "Fusion generation failed with exit code $LASTEXITCODE"
}

$report = Join-Path $repoRoot "results\20260828_showcase\index.html"
Write-Output "Fusion, global placement, interactive viewer and validation report ready: $report"
