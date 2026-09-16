param(
    [Parameter(Mandatory = $true)][string]$RgbdDataset,
    [Parameter(Mandatory = $true)][string]$RgbdBundle
)
$ErrorActionPreference = "Stop"

# Rewrite reconstruction references after relocating the report. The large
# original cloud stays outside the portable bundle, as in the main showcase.
$reportPath = Join-Path $RgbdBundle "validation\validation_report.html"
$reportHtml = Get-Content -LiteralPath $reportPath -Raw
$reportHtml = $reportHtml.Replace("../../merge_simple_full_step10/diagnostics/scene_preview_sampled.ply", "../scene_preview_sampled.ply")
$reportHtml = $reportHtml.Replace("../../merge_simple_full_step10/diagnostics/scene_top_side_preview.png", "../scene_top_side_preview.png")
$reportHtml = $reportHtml.Replace("../../merge_simple_full_step10/merge_pcd_cam0.ply", "../../../../../PhenoFusion3D/data/main/test_plant_20260828120800_best_lighting/merge_simple_full_step10/merge_pcd_cam0.ply")
$reportHtml = $reportHtml.Replace(">Full-resolution PLY</a>", ">Full-resolution PLY (local computer only)</a>")
Set-Content -LiteralPath $reportPath -Value $reportHtml -Encoding utf8 -NoNewline

# The copied report keeps its original ../ image paths. Preserve that layout.
foreach ($folder in @("guided_leaf_measurements", "manual_photos")) {
    $source = Join-Path $RgbdDataset ("validation\" + $folder)
    $destination = Join-Path $RgbdBundle $folder
    New-Item -ItemType Directory -Force -Path $destination | Out-Null
    $images = @(Get-ChildItem -LiteralPath $source -File -Filter "*.png")
    if ($images.Count -eq 0) { throw "No validation images found in $source" }
    $images | Copy-Item -Destination $destination -Force
}
foreach ($plant in @("plant_1", "plant_2", "plant_3")) {
    $destination = Join-Path $RgbdBundle ("software_traits\" + $plant)
    New-Item -ItemType Directory -Force -Path $destination | Out-Null
    foreach ($name in @("plant_overlay.png", "leaf_segments.png")) {
        $source = Join-Path $RgbdDataset ("validation\software_traits\" + $plant + "\" + $name)
        Copy-Item -LiteralPath $source -Destination (Join-Path $destination $name) -Force
    }
}
