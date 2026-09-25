# Third-Party Licenses

PyLog includes the following bundled third-party libraries and depends on several open-source packages.

---

## Bundled Libraries

These files are included directly in the repository under `plugins/ai_assistant/ui/resources/`.

### Ace Editor
- **Files**: `ace.js`, `ext-language_tools.js`, `mode-python.js`, `theme-monokai.js`
- **License**: BSD 3-Clause
- **Homepage**: https://ace.c9.io/
- **Repository**: https://github.com/ajaxorg/ace

### highlight.js
- **Files**: `highlight.min.js`, `highlight.css`
- **Version**: 11.7.0
- **License**: BSD 3-Clause
- **Copyright**: © 2006-2022 Ivan Sagalaev and other contributors
- **Homepage**: https://highlightjs.org/
- **Repository**: https://github.com/highlightjs/highlight.js

### marked
- **Files**: `marked.min.js`
- **Version**: 4.3.0
- **License**: MIT
- **Copyright**: © 2011-2023 Christopher Jeffrey
- **Homepage**: https://marked.js.org/
- **Repository**: https://github.com/markedjs/marked

### QWebChannel.js
- **Files**: `qwebchannel.js`
- **License**: LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only
- **Copyright**: © 2016 The Qt Company Ltd.
- **Homepage**: https://doc.qt.io/qt-6/qwebchannel.html

---

## Python Dependencies

Installed via `pip install -r requirements.txt`. Licenses are listed for reference.

| Package | License | Homepage |
|---------|---------|----------|
| PySide6 | LGPL-3.0 | https://doc.qt.io/qtforpython/ |
| pyqtgraph | MIT | https://www.pyqtgraph.org/ |
| NumPy | BSD-3-Clause | https://numpy.org/ |
| SciPy | BSD-3-Clause | https://scipy.org/ |
| h5py | BSD-3-Clause | https://www.h5py.org/ |
| Matplotlib | PSF (BSD-compatible) | https://matplotlib.org/ |
| dlisio | LGPL-3.0 | https://github.com/equinor/dlisio |
| openai | Apache-2.0 | https://github.com/openai/openai-python |
| requests | Apache-2.0 | https://requests.readthedocs.io/ |
| qasync | BSD-2-Clause | https://github.com/CabbageDevelopment/qasync |
| sniffio | MIT / Apache-2.0 | https://github.com/python-trio/sniffio |
| mcp | MIT | https://github.com/modelcontextprotocol/python-sdk |
