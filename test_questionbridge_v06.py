from decimal import Decimal
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

import test_questionbridge_v02 as tests_v02
import test_questionbridge_v03 as tests_v03

ROOT = Path(__file__).resolve().parent
CONVERTER = ROOT / "questionbridge_v06.py"


class QuestionBridgeV06Tests(unittest.TestCase):
    def check_mc(self, filename, title, points, weights):
        source = ROOT / filename
        self.assertTrue(CONVERTER.is_file(), f"Konverter fehlt: {CONVERTER}")
        self.assertTrue(source.is_file(), f"QTI-Referenzdatei fehlt: {source}")

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "moodle.xml"
            result = subprocess.run(
                [sys.executable, str(CONVERTER), str(source), str(output)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            questions = ET.parse(output).getroot().findall("question")

        self.assertEqual(len(questions), 1)
        question = questions[0]
        self.assertEqual(question.get("type"), "multichoice")
        self.assertEqual(question.findtext("name/text"), title)
        self.assertEqual(question.findtext("single"), "false")
        self.assertEqual(Decimal(question.findtext("defaultgrade")), points)

        answers = question.findall("answer")
        self.assertEqual(len(answers), len(weights))
        self.assertEqual(
            {a.findtext("text"): Decimal(a.attrib["fraction"]) for a in answers},
            weights,
        )

    def test_mc_002_deductions(self):
        self.check_mc(
            "1795438654__0__qti_329.xml", "QB-MC-002", 2,
            {"3": -50, "4": 50, "5": -50, "6": 50},
        )

    def test_mc_003_unequal_weights(self):
        self.check_mc(
            "1795440234__0__qti_329.xml", "QB-MC-003", 4,
            {"3": -25, "4": 25, "5": -25, "6": 75},
        )

    def test_mc_004_three_correct_answers(self):
        self.check_mc(
            "1795443466__0__qti_329.xml", "QB-MC-004", 4,
            {"2": 25, "4": 25, "5": -25, "6": 50},
        )


def load_tests(loader, standard_tests, pattern):
    tests_v02.CONVERTER = CONVERTER
    tests_v03.CONVERTER = CONVERTER
    return unittest.TestSuite([
        loader.loadTestsFromModule(tests_v02),
        loader.loadTestsFromModule(tests_v03),
        standard_tests,
    ])


if __name__ == "__main__":
    unittest.main(verbosity=2)
