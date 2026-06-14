# User Scripts

Place your custom Python scripts in this directory.

Scripts placed here will appear in the **SCRIPTS** tab of the Explorer panel and can be:
- Double-clicked to open in the built-in script editor
- Executed with **Run (Ctrl+R)** from the editor
- Referenced by the AI assistant via `@file:` mentions

## Environment

When executed from the built-in script editor, the following variables are automatically available:
- `db_path` — Path to the currently active well database
- `__file__` — Path to the running script

## Example

```python
from pylog_api import plot_from_db, list_wells

# List all wells in the active database
wells = list_wells(db_path)
print(wells)
```
