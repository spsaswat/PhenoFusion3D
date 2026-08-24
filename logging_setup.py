"""
logging_setup.py
----------------
Application logging, and protection against rospy stealing it.

`rospy.init_node()` calls `logging.config.fileConfig(...)` internally,
which REPLACES every handler on the root logger with rospy's own
(~/.ros/log/<node>.log). Everything the app logs after ROS starts then
vanishes from phenofusion3d.log -- exactly the window we most need on
the lab rig.

So handler installation is idempotent and re-runnable:
`reinstall_handlers()` is called right after every `init_node()` to put
our console + file handlers back.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import platform

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'phenofusion3d.log')

# Tag our handlers so we can recognise them after rospy has been through.
_MARK = '_phenofusion_handler'


def _make_handlers() -> list:
    handlers = []
    fmt = logging.Formatter(
        '%(asctime)s %(levelname)-7s [%(name)s] %(message)s'
    )

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    setattr(console, _MARK, True)
    handlers.append(console)

    try:
        file_h = logging.handlers.RotatingFileHandler(
            LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding='utf-8'
        )
        file_h.setLevel(logging.DEBUG)
        file_h.setFormatter(fmt)
        setattr(file_h, _MARK, True)
        handlers.append(file_h)
    except OSError as e:
        logging.getLogger().warning(
            'Could not open log file %s: %s', LOG_PATH, e
        )
    return handlers


def reinstall_handlers() -> bool:
    """Re-attach our handlers to the root logger if they were dropped.

    Returns True if anything had to be restored -- call this after every
    `rospy.init_node()`. Safe and cheap to call repeatedly.
    """
    root = logging.getLogger()
    if any(getattr(h, _MARK, False) for h in root.handlers):
        return False
    root.setLevel(logging.DEBUG)
    for h in _make_handlers():
        root.addHandler(h)
    root.debug('logging handlers reinstalled (rospy had replaced them)')
    return True


def setup_logging() -> None:
    """Console at INFO, rotating file at DEBUG (phenofusion3d.log next
    to main.py). The file is the one to read when the app misbehaves on
    the lab rig -- it records the full ROS init sequence."""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for h in _make_handlers():
        root.addHandler(h)

    root.info('PhenoFusion3D starting | python=%s | %s | ROS_MASTER_URI=%s',
              platform.python_version(), platform.platform(),
              os.environ.get('ROS_MASTER_URI', '<unset>'))
