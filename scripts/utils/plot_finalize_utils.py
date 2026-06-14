from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QTimer


def schedule_plot_finalize(mw, log_plot, target_sub):
    """Schedule first-frame sync after curves have been injected."""

    def _finalize_ui_pulse():
        if hasattr(log_plot, "set_vertical_scale"):
            log_plot.set_vertical_scale(10)

        if hasattr(log_plot, "scroll_mgr"):
            v_master = log_plot.get_master_viewbox()
            if v_master:
                y_min, y_max = v_master.viewRange()[1]
                log_plot.scroll_mgr.apply_depth_range(y_min, y_max, force=True)

        mw.show()
        mw.raise_()
        target_sub.show()

    QTimer.singleShot(200, _finalize_ui_pulse)


def finalize_plot_ui(mw, target_sub, block, app):
    """Show and refresh UI, optionally entering the Qt event loop."""
    mw.show()
    mw.raise_()
    mw.activateWindow()
    target_sub.show()
    target_sub.raise_()
    target_sub.activateWindow()
    QCoreApplication.processEvents()
    if block:
        if not hasattr(app, "_is_running") or not app._is_running:
            app._is_running = True
            app.exec()
            app._is_running = False
