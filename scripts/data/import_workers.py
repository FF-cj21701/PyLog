import asyncio
import time
from PySide6.QtCore import QObject, Signal
from .dlis_importer import import_dlis
from .dlis_exporter import export_well_to_dlis

class ImportWorker(QObject):
    finished = Signal(object) # Returns well_id or None
    error = Signal(str)
    curve_signal = Signal(str) # Emitted for each curve saved

    def __init__(self, file_path, custom_well_name=None, selected_curves=None):
        super().__init__()
        self.file_path = file_path
        self.custom_well_name = custom_well_name
        self.selected_curves = selected_curves

    async def run_async(self):
        """Asynchronously execute the import using dlisio in a background thread."""
        loop = asyncio.get_event_loop()
        try:
            def progress_callback(status):
                # Signaling across threads is safe for QObject signals
                self.curve_signal.emit(status)
                
            # Offload heavy IO/CPU work to a background thread to keep UI loop responsive
            well_id = await loop.run_in_executor(None, 
                lambda: import_dlis(self.file_path, 
                                     callback=progress_callback, 
                                     custom_well_name=self.custom_well_name,
                                     selected_curves=self.selected_curves)
            )
            
            self.finished.emit(well_id)
            return well_id
        except Exception as e:
            self.error.emit(str(e))
            return None


class ExportWorker(QObject):
    finished = Signal(object)  # Returns export result dict
    error = Signal(str)
    progress = Signal(object)  # Emits progress payload dict

    def __init__(self, well_context, selected_curves, output_path):
        super().__init__()
        self.well_context = well_context
        self.selected_curves = selected_curves
        self.output_path = output_path
        self._last_progress_emit_at = 0.0
        self._last_progress_current = -1

    def _should_emit_progress(self, payload):
        phase = payload.get("phase")
        if phase != "writing_records":
            return True

        current = int(payload.get("current") or 0)
        total = int(payload.get("total") or 0)
        now = time.monotonic()

        # Always emit boundaries and meaningful jumps; otherwise rate-limit
        if current <= 1 or (total and current >= total):
            self._last_progress_emit_at = now
            self._last_progress_current = current
            return True

        if self._last_progress_current < 0 or current - self._last_progress_current >= 100:
            self._last_progress_emit_at = now
            self._last_progress_current = current
            return True

        if now - self._last_progress_emit_at >= 0.05:
            self._last_progress_emit_at = now
            self._last_progress_current = current
            return True

        return False

    async def run_async(self):
        """Asynchronously execute DLIS export in a background thread."""
        loop = asyncio.get_event_loop()
        try:
            def progress_callback(payload):
                if self._should_emit_progress(payload):
                    self.progress.emit(payload)

            result = await loop.run_in_executor(
                None,
                lambda: export_well_to_dlis(
                    self.well_context,
                    self.selected_curves,
                    self.output_path,
                    progress_callback=progress_callback,
                ),
            )

            self.finished.emit(result)
            return result
        except Exception as e:
            self.error.emit(str(e))
            return None
