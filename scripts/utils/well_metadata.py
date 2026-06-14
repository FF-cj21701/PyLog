import sqlite3

from .well_queries import build_folder_map


def get_well_info_snapshot(db, db_path, well_id):
    """Load a well's folders and curve metadata in a shared, read-only shape."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT name FROM wells WHERE id=?", (well_id,))
        well_name_row = cursor.fetchone()
        well_name = well_name_row[0] if well_name_row else str(well_id)

        well_info = {
            "ok": True,
            "id": well_id,
            "name": well_name,
            "folders": [],
            "curves": [],
        }

        cursor.execute("SELECT id, name, parent_id FROM folders WHERE well_id=?", (well_id,))
        for fid, fname, fpid in cursor.fetchall():
            well_info["folders"].append({"id": fid, "name": fname, "parent_id": fpid})

        folder_map = build_folder_map(db, well_id)
        cursor.execute(
            "SELECT id, name, unit, dimensions, shape, dtype, folder_id, val_min, val_max FROM curves WHERE well_id=?",
            (well_id,),
        )
        for cid, cname, cunit, cdims, cshape, cdtype, cfid, vmin, vmax in cursor.fetchall():
            well_info["curves"].append(
                {
                    "id": cid,
                    "name": cname,
                    "folder": folder_map.get(cfid),
                    "unit": cunit,
                    "dimensions": cdims,
                    "shape": cshape,
                    "dtype": cdtype,
                    "folder_id": cfid,
                    "min": vmin,
                    "max": vmax,
                }
            )
        return well_info
    finally:
        conn.close()
