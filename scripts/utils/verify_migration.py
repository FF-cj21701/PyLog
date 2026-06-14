import os
import sqlite3

db_path = 'data/Gangtan1_SL.db'
h5_path = 'data/Gangtan1_SL.h5'

print("-" * 40)
if os.path.exists(h5_path):
    size_mb = os.path.getsize(h5_path) / (1024 * 1024)
    print(f"[OK] H5 File: {os.path.basename(h5_path)} exists.")
    print(f"   - Size: {size_mb:.2f} MB")
else:
    print(f"[ERROR] H5 File missing: {h5_path}")

print("-" * 40)
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    # Check a specific curve
    cur.execute("SELECT name, is_h5, dataset_path, val_min, val_max FROM curves WHERE is_h5 = 1 LIMIT 5")
    rows = cur.fetchall()
    print(f"Metadata Check (First 5 H5 curves):")
    for row in rows:
        print(f"   - {row[0]}: is_h5={row[1]}, path={row[2]}, range=[{row[3]:.2f}, {row[4]:.2f}]")
    conn.close()
else:
    print(f"[ERROR] DB File missing: {db_path}")
print("-" * 40)
