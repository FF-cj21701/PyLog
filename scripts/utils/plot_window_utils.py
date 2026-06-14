from __future__ import annotations

import sys
from typing import Tuple

from PySide6.QtWidgets import QApplication, QMdiSubWindow
from PySide6.QtCore import Qt

from main import MainWindow
from scripts.rendering.plot_widget import LogWidget


def get_or_create_plot_window(
    title: str,
    *,
    show_ai_chat: bool = False,
    show_scripts: bool = False,
) -> Tuple[QApplication, MainWindow, LogWidget, QMdiSubWindow]:
    """Find or create the main window and target log-plot subwindow."""
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")

    mw = None
    for widget in app.topLevelWidgets():
        if hasattr(widget, "mdi_area") and hasattr(widget, "setWindowTitle"):
            mw = widget
            break

    if mw is None:
        mw = MainWindow(show_ai_chat=show_ai_chat, show_scripts=show_scripts)
        mw.setWindowTitle("ALIVE")

    log_plot = None
    target_sub = None
    for sub in mw.mdi_area.subWindowList():
        if sub.windowTitle() == title:
            target_sub = sub
            if isinstance(sub.widget(), LogWidget):
                log_plot = sub.widget()
            break

    if log_plot is None:
        log_plot = LogWidget(None)
        target_sub = QMdiSubWindow()
        target_sub.setWidget(log_plot)
        target_sub.setWindowTitle(title)
        target_sub.setAttribute(Qt.WA_DeleteOnClose)

        if "Log Plot" in title:
            try:
                num = int(title.replace("Log Plot", "").strip())
                if not hasattr(mw, "_plot_count") or num > mw._plot_count:
                    mw._plot_count = num
            except Exception:
                pass
        elif not hasattr(mw, "_plot_count"):
            mw._plot_count = 0

        if mw and hasattr(mw, "handle_plot_selection"):
            log_plot.selectionChanged.connect(mw.handle_plot_selection)

        mw.mdi_area.addSubWindow(target_sub)

    return app, mw, log_plot, target_sub
