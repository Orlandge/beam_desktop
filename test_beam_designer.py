import csv
import tempfile
import unittest
from pathlib import Path

from app import (
    BeamInput,
    PointLoad,
    UniformLoad,
    analyze_beam,
    export_results_csv,
    format_sig,
    open_design,
    save_calculation_sheet,
    save_design,
)


class BeamValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.section = "W12x26"

    def test_simply_supported_uniform_load(self) -> None:
        design = BeamInput(
            "simple",
            20,
            self.section,
            uniform_loads=(UniformLoad(1, 0, 20),),
        )
        result = analyze_beam(design)
        self.assertAlmostEqual(result.reaction_a_kip, 10.0, places=10)
        self.assertAlmostEqual(result.reaction_b_kip, 10.0, places=10)
        self.assertAlmostEqual(abs(result.max_moment_kip_in) / 12, 50.0, places=10)
        self.assertEqual(format_sig(abs(result.max_deflection_in)), "0.609")
        self.assertAlmostEqual(result.deflection_limit_in, 2 / 3, places=10)
        self.assertLessEqual(abs(result.max_deflection_in), result.deflection_limit_in)

    def test_simply_supported_midspan_point_load(self) -> None:
        design = BeamInput(
            "simple",
            20,
            self.section,
            point_loads=(PointLoad(10, 10),),
        )
        result = analyze_beam(design)
        self.assertAlmostEqual(result.reaction_a_kip, 5.0, places=10)
        self.assertAlmostEqual(result.reaction_b_kip, 5.0, places=10)
        self.assertAlmostEqual(abs(result.max_moment_kip_in) / 12, 50.0, places=10)
        self.assertEqual(format_sig(abs(result.max_deflection_in)), "0.487")
        self.assertAlmostEqual(result.deflection_limit_in, 2 / 3, places=10)

    def test_cantilever_end_point_load(self) -> None:
        design = BeamInput(
            "cantilever",
            10,
            self.section,
            point_loads=(PointLoad(1, 10),),
        )
        result = analyze_beam(design)
        self.assertAlmostEqual(result.reaction_a_kip, 1.0, places=10)
        self.assertAlmostEqual(abs(result.fixed_end_moment_kip_in) / 12, 10.0, places=10)
        self.assertAlmostEqual(abs(result.max_moment_kip_in) / 12, 10.0, places=10)
        self.assertEqual(format_sig(abs(result.max_deflection_in)), "0.0974")
        self.assertAlmostEqual(result.deflection_limit_in, 1 / 3, places=10)

    def test_zero_load_on_both_support_conditions(self) -> None:
        for support in ("simple", "cantilever"):
            with self.subTest(support=support):
                result = analyze_beam(BeamInput(support, 20, self.section))
                self.assertEqual(result.reaction_a_kip, 0.0)
                self.assertEqual(result.reaction_b_kip, 0.0)
                self.assertEqual(result.max_shear_kip, 0.0)
                self.assertEqual(result.max_moment_kip_in, 0.0)
                self.assertEqual(result.max_deflection_in, 0.0)

    def test_mixed_partial_and_upward_loads_satisfy_equilibrium(self) -> None:
        design = BeamInput(
            "simple",
            20,
            self.section,
            point_loads=(PointLoad(4, 5), PointLoad(1, 18, "up")),
            uniform_loads=(UniformLoad(0.5, 2, 12),),
        )
        result = analyze_beam(design)
        expected_total_downward = 4 - 1 + 0.5 * (12 - 2)
        self.assertAlmostEqual(
            result.reaction_a_kip + result.reaction_b_kip,
            expected_total_downward,
            places=10,
        )

    def test_invalid_span_load_ranges_and_allowable_are_rejected(self) -> None:
        invalid_designs = (
            BeamInput("simple", 0, self.section),
            BeamInput("simple", 20, self.section, allowable_bending_stress_ksi=0),
            BeamInput("simple", 20, self.section, point_loads=(PointLoad(1, 21),)),
            BeamInput("simple", 20, self.section, point_loads=(PointLoad(-1, 10),)),
            BeamInput("simple", 20, self.section, uniform_loads=(UniformLoad(1, 5, 5),)),
        )
        for design in invalid_designs:
            with self.subTest(design=design), self.assertRaises(ValueError):
                analyze_beam(design)


class FileWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.design = BeamInput(
            "simple",
            20,
            "W12x26",
            allowable_bending_stress_ksi=20,
            point_loads=(PointLoad(3, 5, "up"), PointLoad(10, 10)),
            uniform_loads=(UniformLoad(0.5, 2, 18),),
        )
        self.result = analyze_beam(self.design)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.directory = Path(self.temp_dir.name)

    def test_save_and_open_design_round_trip(self) -> None:
        path = self.directory / "design.beam.json"
        save_design(path, self.design)
        self.assertEqual(open_design(path), self.design)

    def test_open_rejects_malformed_and_unsupported_designs(self) -> None:
        malformed = self.directory / "broken.beam.json"
        malformed.write_text("{", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "valid JSON"):
            open_design(malformed)

        unsupported = self.directory / "future.beam.json"
        unsupported.write_text(
            '{"format":"beam-designer","version":2}', encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "unsupported format or version"):
            open_design(unsupported)

        invalid_direction = self.directory / "invalid-direction.beam.json"
        invalid_direction.write_text(
            '{"format":"beam-designer","version":1,"support":"simple",'
            '"span_ft":20,"section":"W12x26","point_loads":['
            '{"magnitude_kip":1,"position_ft":10,"direction":[]}],'
            '"uniform_loads":[]}',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "invalid direction"):
            open_design(invalid_direction)

    def test_csv_has_required_columns_ends_and_load_locations(self) -> None:
        path = self.directory / "results.csv"
        export_results_csv(path, self.design, self.result)
        with path.open(encoding="utf-8-sig", newline="") as file:
            rows = list(csv.DictReader(file))
        self.assertEqual(
            list(rows[0]),
            ["beam_length_ft", "x_ft", "V_kip", "M_kip_ft", "deflection_in"],
        )
        sample_positions = [float(row["x_ft"]) for row in rows]
        self.assertIn(0.0, sample_positions)
        self.assertIn(20.0, sample_positions)
        self.assertIn(5.0, sample_positions)
        self.assertIn(10.0, sample_positions)
        self.assertIn(2.0, sample_positions)
        self.assertIn(18.0, sample_positions)
        self.assertTrue(all(float(row["beam_length_ft"]) == 20 for row in rows))

    def test_calculation_sheet_is_a_pdf(self) -> None:
        path = self.directory / "calculation-sheet.pdf"
        save_calculation_sheet(path, self.design, self.result)
        content = path.read_bytes()
        self.assertTrue(content.startswith(b"%PDF-"))
        self.assertGreater(len(content), 10_000)


if __name__ == "__main__":
    unittest.main()
