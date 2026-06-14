import asyncio
from PySide6.QtCore import QObject, Signal
from .dlis_importer import import_dlis

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
