class APIDocumentation:
    """Detailed documentation of PyLog built-in APIs for AI reference."""

    CORE_API_SUMMARY = """
- `list_wells(db_path=None)`: List wells from the active or specified database.
- `save_curve(well, curve_name, values, ...)`: Persist calculated curve data back into the well database.
- `plot(well=None, curves=None, data_list=None, title='Plot', ...)`: Unified plotting entry for database-backed or in-memory data.
"""

    DOCS_BY_TOPIC = {
        "data_retrieval": """
### Data Retrieval
- `list_wells(db_path=None)`
    - Description: Return all wells. If `db_path` is omitted, the project data directory is scanned.
    - Parameters: `db_path` (str, optional)
    - Returns: Unified result with `ok`, `summary`, `data`, and typically `wells`.
- `get_well_info(well, db_path=None)`
    - Description: Return full well information, including folders and curve hierarchy.
    - Parameters: `well` (str/int), `db_path` (str, optional)
    - Returns: Unified result with `ok`, `summary`, and well metadata in `data`.
- `list_curves(well, db_path=None)`
    - Description: Return all curves for a well, including units and ranges where available.
    - Parameters: `well` (str/int), `db_path` (str, optional)
    - Returns: Unified result with `ok`, `summary`, and curve metadata in `data` or `curves`.
- `get_curve_info(well, curve_name, db_path=None)`
    - Description: Return metadata for a specific curve. Path-like names such as `FRAME0/GR` are supported.
    - Parameters: `well` (str/int), `curve_name` (str), `db_path` (str, optional)
    - Returns: Unified result with `ok`, `summary`, and curve metadata in `data`.
- `get_depth_data(well, folder=None, db_path=None)`
    - Description: Find the most suitable depth curve, usually `DEPT` or `DEPTH`, and return numeric values.
    - Parameters: `well` (str/int), `folder` (str, optional), `db_path` (str, optional)
    - Returns: Result payload containing depth-curve metadata and values.
- `get_curve_data(well, curve_name, db_path=None)`
    - Description: Return raw curve values for analysis or scripting.
    - Parameters: `well` (str/int), `curve_name` (str), `db_path` (str, optional)
    - Returns: Raw numeric array on success, or an error payload on failure.
""",
        "data_manipulation": """
### Data Manipulation and Persistence
- `save_curve(well, curve_name, values, unit='', folder=None, db_path=None)`
    - Description: Save a generated numeric array into the well database.
    - Parameters:
        - `well`: Well name or ID
        - `curve_name`: New curve name, for example `POR_AI`
        - `values`: Numeric array, list, or NumPy array
        - `unit`: Curve unit (optional)
        - `folder`: Target folder such as `FRAME0` (optional)
        - `db_path`: Explicit database path (optional)
    - Returns: Unified result with `ok`, `summary`, and saved-curve metadata in `data`.
""",
        "analysis": """
### Analysis
- `analyze_data(values)`
    - Description: Run statistical analysis on a numeric array.
    - Parameters: `values` (list or numpy array)
    - Returns: Unified result with `ok`, `summary`, and analysis metrics in `data` or `analysis`.
- `analyze_curve(well, curve_name, db_path=None)`
    - Description: Load a curve and immediately run statistical analysis.
    - Parameters: `well` (str/int), `curve_name` (str), `db_path` (str, optional)
    - Returns: Unified result with `ok`, `summary`, and analysis metrics in `data`.
""",
        "visualization": """
### Visualization
- `plot(well=None, curves=None, data_list=None, title="Log Plot", db_path=None, ...)`
    - Description: Unified plotting API. Supports direct database plotting and in-memory plotting.
    - Parameters:
        - `well`: Well name (optional, used for depth lookup when needed)
        - `curves`: Database curve names for database-backed plotting
        - `data_list`: In-memory curve payloads such as `{'values': [], 'depth': [], 'name': 'POR'}`
        - `db_path`: Database path (optional)
        - `accum_fill`: Enable cumulative fill (optional)
        - `colors`: Optional color list
    - Returns: Unified result with `ok`, `summary`, and plot metadata in `data`.
- `plot_log_curves(data_list, title="Log Plot 1", accum_fill=False)`
    - Description: Plot in-memory curve data.
    - Returns: Unified result with `ok`, `summary`, and plot metadata.
""",
        "usage_guidelines": """
### Usage Guidelines
1. `list_wells` may return database-aware metadata. When a well is outside the active database, pass its `db_path` into follow-up calls.
2. Prefer built-in APIs over custom code when the capability already exists.
3. Fall back to custom Python only for logic not covered by the built-in APIs.
4. When tools wrap these APIs, prefer the unified contract fields `ok`, `summary`, `content`, and `data`.
""",
    }

    @classmethod
    def get_full_docs(cls):
        """Return the combined documentation text."""
        return "# ALIVE API Documentation\n\n" + "\n".join(cls.DOCS_BY_TOPIC.values())


APIDocumentation.PYLOG_API_DOCS = APIDocumentation.get_full_docs()
