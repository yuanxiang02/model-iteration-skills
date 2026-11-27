"""Helpers shared by the test modules."""

import tempfile
import unittest
from pathlib import Path


def symlinks_supported():
    """True when this process may create symbolic links.

    Windows requires SeCreateSymbolicLinkPrivilege (administrator) or Developer
    Mode. Several security tests build their fixture with ``Path.symlink_to``; on
    a host that cannot create the fixture the check is unrunnable rather than
    failing, so it is skipped with an explicit reason.
    """
    with tempfile.TemporaryDirectory(prefix="mih-symlink-probe-") as directory:
        target = Path(directory) / "target.txt"
        target.write_text("probe", encoding="utf-8")
        link = Path(directory) / "link.txt"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            return False
        return link.is_symlink()


SYMLINK_SKIP = (
    "requires symbolic-link privilege (run as administrator or enable "
    "Windows Developer Mode)"
)

requires_symlinks = unittest.skipUnless(symlinks_supported(), SYMLINK_SKIP)
