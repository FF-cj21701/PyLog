# Contributing to PyLog

Thank you for your interest in contributing to PyLog! This guide will help you get started.

## 🚀 Getting Started

1. **Fork** the repository on GitHub
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/PyLog.git
   cd PyLog
   ```
3. **Create a virtual environment** and install dependencies:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate   # Windows
   pip install -r requirements.txt
   ```
4. **Create a branch** for your changes:
   ```bash
   git checkout -b feature/your-feature-name
   ```

## 📋 Development Guidelines

### Code Style
- Follow **PEP 8** conventions
- Use **type hints** where practical
- Write **docstrings** for public classes and functions
- Keep comments bilingual (English preferred for code comments; Chinese OK for UI strings)

### Commit Messages
- Use clear, descriptive commit messages
- Prefix with a category when applicable:
  - `feat:` — New feature
  - `fix:` — Bug fix
  - `docs:` — Documentation changes
  - `refactor:` — Code refactoring
  - `test:` — Adding or updating tests
  - `perf:` — Performance improvement

### Testing
- Run existing tests before submitting:
  ```bash
  python -m unittest discover tests
  ```
- Add tests for new features when possible
- Verify the application launches correctly: `python main.py`

## 🔀 Pull Request Process

1. **Update documentation** if your changes affect user-facing behavior
2. **Ensure tests pass** and the app runs without errors
3. **Keep PRs focused** — one feature or fix per PR
4. **Describe your changes** clearly in the PR description
5. **Reference related issues** if applicable (e.g., "Closes #42")

## 🐛 Bug Reports

When filing a bug report, please include:
- Python version and OS
- Steps to reproduce the issue
- Expected vs. actual behavior
- Error messages or screenshots if applicable

## 💡 Feature Requests

Feature requests are welcome! Please:
- Check existing issues to avoid duplicates
- Describe the use case and expected behavior
- Explain why this feature would be useful to other users

## 📁 Project Structure Overview

| Directory | Purpose |
|-----------|---------|
| `core/` | Application configuration and plugin interface |
| `scripts/data/` | Database management, DLIS import, templates |
| `scripts/rendering/` | Plot widget, track rendering, fill engine |
| `scripts/tracks/` | Track container hierarchy |
| `scripts/ui/` | Explorer, dialogs, menus, themes |
| `scripts/utils/` | Shared utilities, workers, curve loading |
| `plugins/ai_assistant/` | AI assistant plugin (agent, tools, UI) |
| `pylog_api/` | Public Python API |

## 📜 License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
