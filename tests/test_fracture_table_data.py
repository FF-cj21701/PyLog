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


if __name__ == "__main__":
    unittest.main()
