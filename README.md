# <img src="icons/restore.png" width="28" align="center"> PyLog (ALIVE)

**AI-powered well log visualization and data analysis platform**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-green.svg)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/GUI-PySide6-orange.svg)](https://doc.qt.io/qtforpython/)

---

## ✨ Features

### 🎯 Core Visualization
- **Multi-track log display** — 1D curves and 2D borehole images in a unified track system
- **HDF5-backed storage** — Handles wells with 100,000+ depth points at 60 FPS via viewport-aware lazy loading and tiled rendering
- **Drag & drop** — Drag curves from the Explorer into plot tracks; drop into the Quick Add zone to auto-create new tracks
- **Real-time interaction** — Smooth scrolling, zoom (mouse wheel + middle-button drag), depth synchronization across all tracks
- **Logarithmic scale** — Full log-scale support for resistivity curves and image tracks with automatic colorbar adaptation
- **Curve fill** — Baseline fill, cross-fill between curves, and accumulative (stacked lithology) fill modes
- **Template system** — Save / load plot configurations (`.plt`) for repeatable workflows

### 🤖 AI Assistant (Plugin)
- **Natural language control** — "Plot GR and NPHI for Well-01", "Enable accumulative fill on Track 2"
- **Agentic execution** — Multi-step task planning, tool calling, code generation and execution with a built-in terminal
- **Context awareness** — Automatic metadata extraction from Explorer selections and plot interactions (`@` mentions)
- **OpenAI-compatible** — Works with OpenAI, DeepSeek, Moonshot, Ollama, or any OpenAI-compatible endpoint
- **MCP support** — Optional Model Context Protocol server integration for extended tool capabilities

### 📊 Data Management
- **DLIS import** — Parse DLIS files with curve selection, well naming, and unit auto-conversion
- **Custom curve entry** — Manual table input or Excel paste with undo support (Ctrl+Z, up to 30 steps)
- **Multi-well database** — SQLite + HDF5 per well, with folder organization and cut/copy/paste operations

### 🎨 Themes & Export
- **4 built-in themes** — Light, Dark, Sakura (midnight purple/pink), and Manga (ink-on-paper aesthetic)
- **High-quality export** — JPG / PDF (A0–A4 paged) up to 600 DPI with seamless multi-page stitching
- **Clipboard integration** — Copy plots as SVG + high-resolution PNG for Office documents

### 🔧 Scripting & API
- **Python API** — `plot_log_curves()` and `plot_from_db()` for programmatic visualization
- **Built-in script editor** — Ace-based editor with syntax highlighting, auto-format (PEP 8), and run/save shortcuts
- **Variable explorer** — MATLAB-style workspace inspector for script output

---

## 🚀 Quick Start

### Prerequisites
- Python 3.10 or higher
- pip

### Installation

```bash
# Clone the repository
git clone https://github.com/cj21701/PyLog.git
cd PyLog

# Create virtual environment (recommended)
python -m venv .venv

# Activate (Windows)
.venv\Scripts\activate
# Activate (macOS/Linux)
# source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Run

```bash
python main.py
```

### Import Data

1. **File → Import DLIS...** to load a `.dlis` well log file
2. Select curves and confirm the well name
3. The well appears in the **Explorer** panel — drag curves into the plot area

### Scripting Example

```python
import numpy as np
from pylog_api import plot_log_curves

depth = np.arange(1000, 2000, 0.1)
gr = np.random.normal(50, 15, len(depth))

plot_log_curves([
    {'name': 'GR', 'depth': depth, 'values': gr, 'color': '#2E8B57'}
], title="My First Plot")
```

---

## 📁 Project Structure

```
PyLog/
├── main.py                  # Application entry point
├── core/                    # App configuration & plugin interface
├── scripts/                 # Core modules
│   ├── data/                # DB manager, DLIS importer, template system
│   ├── rendering/           # Plot widget, track rendering, fill engine, tiled images
│   ├── tracks/              # Track containers (depth, curve, image, accumulative)
│   ├── ui/                  # Explorer, dialogs, menus, theme engine
│   └── utils/               # Workers, loggers, curve loading, plot utilities
├── plugins/
│   └── ai_assistant/        # AI assistant plugin
│       ├── ai_core/         # Agent state machine, tool dispatch, planning
│       ├── services/        # Chat service, skill service
│       ├── tools/           # Tool implementations (file, search, plot, verify...)
│       └── ui/              # Chat UI (WebEngine), settings, script editor
├── pylog_api/               # Public Python API for scripting
├── examples/                # Demo scripts
├── docs/                    # Documentation & changelogs
├── data/                    # Well databases (user data, git-ignored)
└── scripts_user/            # User scripts directory
```

---

## 🛠️ Configuration

### AI Assistant Setup

1. Open the AI Assistant panel (**AI Assistant** button or `Ctrl+Shift+A`)
2. Click the **Settings** gear icon
3. Configure a connection profile:
   - **Provider**: OpenAI / DeepSeek / Moonshot / Ollama / Custom
   - **API Key**: Your API key
   - **Base URL**: API endpoint (auto-filled for known providers)
   - **Model**: Model name (e.g., `gpt-4o`, `deepseek-chat`)
4. Optionally configure the **file whitelist** for AI file access security

### Themes

Switch themes via **View → Theme** in the menu bar:
- **Light** — Clean, professional look
- **Dark** — Teal-accented dark mode
- **Sakura** — Midnight purple with hot pink accents
- **Manga** — Ink-on-paper aesthetic with hard borders

---

## 📖 Documentation

- [Changelog](docs/CHANGELOG.md) — Version history and release notes

---

## 🤝 Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- [PySide6](https://doc.qt.io/qtforpython/) — Qt for Python GUI framework
- [pyqtgraph](https://www.pyqtgraph.org/) — Fast scientific plotting
- [dlisio](https://github.com/equinor/dlisio) — DLIS file parser
- [HDF5 / h5py](https://www.h5py.org/) — High-performance data storage
- [geoscience-skills](https://github.com/SteadfastAsArt/geoscience-skills) — AI-powered geoscience assistant capabilities

---

> [!NOTE]
> This project was developed by AI under the guidance and direction of the developer, and the project documentation was written by AI.

