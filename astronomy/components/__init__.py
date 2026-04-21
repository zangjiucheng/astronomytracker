"""Subpackage containing modular user interface components.

Each module in this package defines a single widget or group of
widgets used by the astronomy tracker GUI.  The components are
designed to be attached back onto the parent window instance so
that the existing logic can continue to reference attributes on the
window.  This approach isolates the widget construction from the
business logic of the main window and encourages a cleaner
architecture.
"""

__all__ = [
    "controls_tab",
    "status_tab",
    "plots_tab",
]