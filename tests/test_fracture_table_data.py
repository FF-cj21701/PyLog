import unittest

from scripts.data.fracture_table_data import build_fracture_table_data


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


if __name__ == "__main__":
    unittest.main()
