#!/bin/bash
# install/appimage/entrypoint.sh
# Launches PhenoFusion3D from inside the AppImage.
#
# Runs from $APPDIR (set by the AppImage runtime). $PYTHON is the
# bundled interpreter provided by python-appimage.
#
# We extend sys.path with /opt/ros/<distro>/lib/python3/dist-packages
# (when present) so the ROS capture backend stays usable on lab Linux
# machines without bundling rospy into the AppImage. Same idea for
# pyrealsense2 if it's installed system-wide.

set -e

# Point Qt at the bundled platform plugins. PyQt5 ships its own copy
# under site-packages/PyQt5/Qt5/plugins; the bundled Python knows
# where to find them, but distro Qt env vars can hijack it -- unset
# them to be safe.
unset QT_PLUGIN_PATH
unset QT_QPA_PLATFORM_PLUGIN_PATH

# Allow ROS / pyrealsense2 from host if present (do NOT add to
# PYTHONPATH unconditionally -- only if rospy actually exists there).
ROS_DISTROS=(noetic humble jazzy)
EXTRA_PATH=""
for d in "${ROS_DISTROS[@]}"; do
    candidate="/opt/ros/${d}/lib/python3/dist-packages"
    if [ -d "${candidate}" ]; then
        EXTRA_PATH="${candidate}${EXTRA_PATH:+:${EXTRA_PATH}}"
    fi
done

if [ -n "${EXTRA_PATH}" ]; then
    export PYTHONPATH="${EXTRA_PATH}${PYTHONPATH:+:${PYTHONPATH}}"
fi

# `phenofusion3d` is the console script declared in pyproject.toml
# ([project.scripts]); python-appimage installs it under
# ${APPDIR}/opt/python<ver>/bin/, which is on PATH inside the AppRun.
exec phenofusion3d "$@"
