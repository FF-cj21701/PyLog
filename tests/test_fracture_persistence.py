import os
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scripts.data.db_manager import DBManager
from scripts.rendering.fracture_annotations import (
    FRACTURE_TYPE_STYLES,
    build_fracture_annotation,
)


class FracturePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "fractures.db")
        self.db = DBManager(self.db_path)
        self.well_id = self.db.save_well("DemoWell")

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_and_load_fracture_interpretations_round_trip_payload(self):
        annotation = build_fracture_annotation(
            [[0, 1000.0], [90, 1000.1], [180, 1000.2]],
            fracture_type="Bedding",
            color=FRACTURE_TYPE_STYLES["Bedding"]["color"],
            name="Bedding 1",
        )
        annotation["source_curve_id"] = 11
        annotation["source_curve_name"] = "QGEO_RES_DYN"
        annotation["source_track_label"] = "Track 1 / QGEO_RES_DYN"
        annotation["target_track_label"] = "Track 1 / QGEO_RES_DYN"

        inserted = self.db.save_fracture_interpretations(self.well_id, [annotation])
        loaded = self.db.get_fracture_interpretations(self.well_id)

        self.assertEqual(len(inserted), 1)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["interpretation_id"], inserted[0])
        self.assertEqual(loaded[0]["fracture_type"], "Bedding")
        self.assertIn("center_depth", loaded[0])
        self.assertIn("dip_height", loaded[0])
        self.assertIn("image_azimuth", loaded[0])
        self.assertIn("apparent_dip", loaded[0])
        self.assertEqual(loaded[0]["source_curve_name"], "QGEO_RES_DYN")
        self.assertEqual(loaded[0]["target_track_label"], "Track 1 / QGEO_RES_DYN")

    def test_save_fracture_interpretations_replaces_well_results_by_default(self):
        first = build_fracture_annotation(
            [[0, 1000.0], [90, 1000.1], [180, 1000.2]],
            name="First",
        )
        second = build_fracture_annotation(
            [[0, 1001.0], [90, 1001.1], [180, 1001.2]],
            name="Second",
        )

        self.db.save_fracture_interpretations(self.well_id, [first])
        self.db.save_fracture_interpretations(self.well_id, [second])
        loaded = self.db.get_fracture_interpretations(self.well_id)

        self.assertEqual([item["name"] for item in loaded], ["Second"])


if __name__ == "__main__":
    unittest.main()
