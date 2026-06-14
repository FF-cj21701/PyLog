from typing import Any, Dict, List, Optional


def _get_suggestions(target: str, candidates: List[str], n: int = 3) -> List[str]:
    if not target or not candidates:
        return []
    import difflib

    return difflib.get_close_matches(str(target), [str(c) for c in candidates], n=n, cutoff=0.5)


def build_curve_lookup(curves, folder_map: Optional[Dict[int, str]] = None) -> Dict[str, Any]:
    folder_map = folder_map or {}
    rows_by_name: Dict[str, List[tuple]] = {}
    row_by_path: Dict[str, tuple] = {}
    available_names: List[str] = []

    for row in curves:
        cid, cname, _unit, _shape, fid = row[:5]
        name_str = str(cname)
        rows_by_name.setdefault(name_str, []).append(row)

        folder_name = folder_map.get(fid, "")
        if folder_name:
            full_path = f"{folder_name}/{name_str}"
            row_by_path[full_path] = row
            available_names.append(full_path)
        else:
            available_names.append(name_str)

    return {
        "rows_by_name": rows_by_name,
        "row_by_path": row_by_path,
        "available_names": available_names,
    }


def resolve_curve_row(curve_name: str, curves, folder_map: Optional[Dict[int, str]] = None) -> Dict[str, Any]:
    lookup = build_curve_lookup(curves, folder_map=folder_map)
    rows_by_name = lookup["rows_by_name"]
    row_by_path = lookup["row_by_path"]
    available_names = lookup["available_names"]

    target_row = None
    if "/" in curve_name:
        target_row = row_by_path.get(curve_name)
        if not target_row:
            curve_name_upper = curve_name.upper()
            for path, row in row_by_path.items():
                if path.upper() == curve_name_upper:
                    target_row = row
                    break
    else:
        rows = rows_by_name.get(curve_name)
        if not rows:
            curve_name_upper = curve_name.upper()
            for simple_name, row_list in rows_by_name.items():
                if simple_name.upper() == curve_name_upper:
                    rows = row_list
                    break

        if rows:
            if len(rows) > 1:
                suggestions = []
                for row in rows:
                    folder_name = (folder_map or {}).get(row[4], "Unknown")
                    suggestions.append(f"{folder_name}/{row[1]}")
                return {
                    "ok": False,
                    "error": f"Curve '{curve_name}' is ambiguous. Found in multiple folders.",
                    "suggestions": suggestions,
                    "action_hint": "Please specify the folder path, e.g., 'FRAME0/GR'.",
                    "error_code": "curve_ambiguous",
                }
            target_row = rows[0]

    if target_row:
        return {"ok": True, "row": target_row}

    suggestions = _get_suggestions(curve_name, available_names)
    return {
        "ok": False,
        "error": f"Curve '{curve_name}' not found.",
        "suggestions": suggestions,
        "action_hint": "Try using path like 'Folder/CurveName'.",
        "error_code": "curve_not_found",
    }


def curve_row_to_dict(row: tuple, folder_map: Optional[Dict[int, str]] = None) -> Dict[str, Any]:
    """Convert a curve metadata row into a stable structured payload."""
    if not row:
        return {}

    curve_id = row[0]
    curve_name = row[1]
    unit = row[2]
    shape = row[3]
    folder_id = row[4]
    vmin = row[5] if len(row) > 5 else None
    vmax = row[6] if len(row) > 6 else None

    return {
        "ok": True,
        "id": curve_id,
        "name": str(curve_name),
        "folder": (folder_map or {}).get(folder_id),
        "unit": str(unit) if unit else "",
        "shape": str(shape) if shape else "",
        "folder_id": folder_id,
        "min": vmin,
        "max": vmax,
    }
