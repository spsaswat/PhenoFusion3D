#!/usr/bin/env bash
# install/build_appimage.sh
# ---------------------------------------------------------------
# Build a single-file PhenoFusion3D-x86_64.AppImage that lab users
# can run on any modern Linux without installing Python, PyQt5, or
# Open3D. The bundled Python interpreter comes from python-appimage's
# manylinux base image.
#
# Usage:
#     chmod +x install/build_appimage.sh
#     ./install/build_appimage.sh                 # builds for Python 3.11
#     PY_VERSION=3.10 ./install/build_appimage.sh # pin a specific Python
#     OUT_DIR=dist  ./install/build_appimage.sh   # change output directory
#
# Output:
#     dist/PhenoFusion3D-<version>-x86_64.AppImage
#
# Requirements (build host):
#     - Linux x86_64 (glibc; AppImage is glibc-only)
#     - Python 3.10+ on PATH (used only to run python-appimage)
#     - FUSE 2 *only if* you want to RUN the resulting AppImage on
#       the build host. Building does not require FUSE.
#     - Internet access (downloads the python-appimage base image
#       and pip-installs deps the first time).

set -euo pipefail

# ---------------------------------------------------------------- config

PY_VERSION="${PY_VERSION:-3.11}"
OUT_DIR="${OUT_DIR:-dist}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RECIPE_SRC="${PROJECT_ROOT}/install/appimage"
BUILD_DIR="${PROJECT_ROOT}/build/appimage"
STAGED_RECIPE="${BUILD_DIR}/recipe"
STAGED_PROJECT="${BUILD_DIR}/project"

VERSION="$(grep -E '^version\s*=' "${PROJECT_ROOT}/pyproject.toml" \
            | head -n1 | sed -E 's/version\s*=\s*"([^"]+)"/\1/')"
VERSION="${VERSION:-0.0.0}"

echo "[appimage] Project root : ${PROJECT_ROOT}"
echo "[appimage] Version      : ${VERSION}"
echo "[appimage] Python target: ${PY_VERSION}"
echo "[appimage] Output dir   : ${OUT_DIR}"

# ---------------------------------------------------------------- prereqs

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found on PATH." >&2; exit 1
fi

if [ "$(uname -s)" != "Linux" ]; then
    echo "ERROR: AppImage can only be BUILT on Linux." >&2; exit 1
fi

# Use a build-side venv so python-appimage doesn't pollute the host.
BUILD_VENV="${BUILD_DIR}/venv"
if [ ! -d "${BUILD_VENV}" ]; then
    echo "[appimage] Creating build venv at ${BUILD_VENV}..."
    mkdir -p "${BUILD_DIR}"
    python3 -m venv "${BUILD_VENV}"
fi
# shellcheck disable=SC1091
source "${BUILD_VENV}/bin/activate"
python -m pip install --quiet --upgrade pip
python -m pip install --quiet "python-appimage>=1.3"

# ---------------------------------------------------------------- stage

# Stage a clean copy of the project so the recipe's `pip install .`
# (declared in install/appimage/requirements.txt as the bare ".")
# resolves to a known location -- not the entire repo with venvs and
# captured datasets in it.
echo "[appimage] Staging project tree..."
rm -rf "${STAGED_PROJECT}" "${STAGED_RECIPE}"
mkdir -p "${STAGED_PROJECT}" "${STAGED_RECIPE}"

# Use rsync so we can exclude bulky / irrelevant directories.
rsync -a \
    --exclude='/venv' \
    --exclude='/build' \
    --exclude='/dist' \
    --exclude='/data' \
    --exclude='/.git' \
    --exclude='__pycache__' \
    --exclude='*.egg-info' \
    --exclude='*.AppImage' \
    --exclude='/stakeholder_reference' \
    "${PROJECT_ROOT}/" "${STAGED_PROJECT}/"

# Copy recipe files. Rewrite the trailing "." in requirements.txt so
# pip installs from the staged project path, regardless of where
# python-appimage runs pip from internally.
cp "${RECIPE_SRC}/phenofusion3d.desktop" "${STAGED_RECIPE}/"
cp "${RECIPE_SRC}/entrypoint.sh"         "${STAGED_RECIPE}/entrypoint"
chmod +x "${STAGED_RECIPE}/entrypoint"

# Generate icon (PNG) on-the-fly from a minimal SVG if no icon exists
# in the project. python-appimage requires <appname>.png next to the
# .desktop file.
ICON_PATH="${RECIPE_SRC}/phenofusion3d.png"
if [ ! -f "${ICON_PATH}" ]; then
    echo "[appimage] No icon at ${ICON_PATH}; generating a placeholder..."
    python - <<'PY' "${ICON_PATH}"
import sys, struct, zlib
out = sys.argv[1]
# Minimal 256x256 solid-colour PNG (forest green -- "plant"). Hand-rolled
# to avoid pulling Pillow into the build deps.
W = H = 256
def png_chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))
sig = b'\x89PNG\r\n\x1a\n'
ihdr = struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)
row = b'\x00' + bytes([0x2e, 0x7d, 0x32]) * W  # filter byte + RGB
raw = row * H
idat = zlib.compress(raw, 9)
with open(out, 'wb') as f:
    f.write(sig)
    f.write(png_chunk(b'IHDR', ihdr))
    f.write(png_chunk(b'IDAT', idat))
    f.write(png_chunk(b'IEND', b''))
PY
fi
cp "${ICON_PATH}" "${STAGED_RECIPE}/phenofusion3d.png"

# requirements.txt: replace the trailing "." with the absolute staged
# project path so pip resolves it deterministically.
sed -e "s|^\\.\\s*$|${STAGED_PROJECT}|" \
    "${RECIPE_SRC}/requirements.txt" > "${STAGED_RECIPE}/requirements.txt"

# ---------------------------------------------------------------- build

mkdir -p "${PROJECT_ROOT}/${OUT_DIR}"
cd "${PROJECT_ROOT}/${OUT_DIR}"

echo "[appimage] Running python-appimage build app..."
python -m python_appimage build app -p "${PY_VERSION}" "${STAGED_RECIPE}"

# python-appimage names the output <appname>-<arch>.AppImage; rename
# to include the project version for traceability.
SRC_APPIMAGE="$(ls -1t PhenoFusion3D-*.AppImage 2>/dev/null | head -n1 || true)"
if [ -z "${SRC_APPIMAGE}" ]; then
    echo "ERROR: python-appimage did not produce a .AppImage file." >&2
    exit 1
fi
DEST_APPIMAGE="PhenoFusion3D-${VERSION}-x86_64.AppImage"
if [ "${SRC_APPIMAGE}" != "${DEST_APPIMAGE}" ]; then
    mv -f "${SRC_APPIMAGE}" "${DEST_APPIMAGE}"
fi
chmod +x "${DEST_APPIMAGE}"

echo
echo "[appimage] Done."
echo "    ${PROJECT_ROOT}/${OUT_DIR}/${DEST_APPIMAGE}"
echo
echo "Run with:"
echo "    chmod +x ${DEST_APPIMAGE}"
echo "    ./${DEST_APPIMAGE}"
echo
echo "If FUSE is missing on the target machine:"
echo "    ./${DEST_APPIMAGE} --appimage-extract-and-run"
