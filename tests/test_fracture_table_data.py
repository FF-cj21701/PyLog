import math
import unittest

from scripts.data.fracture_table_data import build_fracture_table_data, format_fracture_table_value


class FractureTableDataTests(unittest.TestCase):
    def test_build_fracture_table_data_formats_rows_and_depth_units(self):
        annotations = [{
            "center_depth": 7532.1851,
            "fracture_type": "Conductive",
            "dip_height": 0.0444,
            "image_azimuth": 254.5371,
            "apparent_dip": None,
            "source_curve_name": "QGEO_RES_DYN",
            "depth_unit": "m",
        }]

        headers, rows = build_fracture_table_data(annotations)

        self.assertEqual(headers[0], "Center Depth (m)")
        self.assertEqual(headers[2], "Dip Height (m)")
        self.assertEqual(rows, [[
            "7532.185",
            "Conductive",
            "0.044",
            "254.537",
            "",
            "QGEO_RES_DYN",
        ]])

    def test_non_finite_and_invalid_numeric_values_are_blank(self):
        self.assertEqual(format_fracture_table_value(None), "")
        self.assertEqual(format_fracture_table_value("invalid"), "")
        self.assertEqual(format_fracture_table_value(math.nan), "")
        self.assertEqual(format_fracture_table_value(math.inf), "")
        self.assertEqual(format_fracture_table_value(-math.inf), "")

    def test_table_without_depth_unit_does_not_guess_units(self):
        headers, rows = build_fracture_table_data([{
            "offset": 1000.0,
            "fracture_type": "Bedding",
            "amplitude": 0.1,
            "source_track_label": "Track 1",
        }])

        self.assertEqual(headers[0], "Center Depth")
        self.assertEqual(headers[2], "Dip Height")
        self.assertEqual(rows[0][0], "1000.000")
        self.assertEqual(rows[0][2], "0.100")
        self.assertEqual(rows[0][5], "Track 1")

    def test_ai_pick_evidence_columns_are_added_when_available(self):
        headers, rows = build_fracture_table_data([{
            "center_depth": 8074.84,
            "fracture_type": "Conductive",
            "dip_height": 0.23,
            "image_azimuth": 125.0,
            "apparent_dip": 3.2,
            "source_curve_name": "CONS_RES_DYN",
            "evidence_id": "EV-abc123",
            "needs_review": True,
            "confidence": 0.72,
            "source_window_indices": [2, 3],
            "source_candidate_ids": ["W2-C1", "W3-C1"],
            "local_completeness": {"available": True, "complete": False},
            "cross_window_corroboration": {"support_count": 2, "fit_acceptable": True},
            "continuity_reason": "visible partial sinusoid across adjacent pads",
        }])

        self.assertEqual(headers[-6:], [
            "Evidence ID",
            "AI Status",
            "AI Confidence",
            "Source Windows",
            "Source Candidates",
            "Evidence Summary",
        ])
        self.assertEqual(rows[0][-6:], [
            "EV-abc123",
            "Needs review",
            "0.72",
            "2, 3",
            "W2-C1, W3-C1",
            "local incomplete | 2 window support; fit ok | visible partial sinusoid across adjacent pads",
        ])


if __name__ == "__main__":
    unittest.main()
