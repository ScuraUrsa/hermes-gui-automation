"""Drivers execute procedure steps: desktop (Windows/Linux), browser, dry-run."""

from hermes_teach.drivers.base import Driver, DriverError, DryRunDriver

__all__ = ["Driver", "DriverError", "DryRunDriver", "make_desktop_driver"]


def make_desktop_driver(**kwargs):  # type: ignore[no-untyped-def]
    from hermes_teach.drivers.desktop import DesktopDriver
    return DesktopDriver(**kwargs)
