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
CONVERTER = ROOT / "questionbridge_v04.py"
FIXTURE = ROOT / "1795438654__0__qti_329.xml"


class QuestionBridgeV04Tests(unittest.TestCase):
    def test_multiple_choice_with_deductions(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "moodle.xml"
            result = subprocess.run(
                [sys.executable, str(CONVERTER), str(FIXTURE), str(output)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            questions = ET.parse(output).getroot().findall("question")
            self.assertEqual(len(questions), 1)
            question = questions[0]
            self.assertEqual(question.get("type"), "multichoice")
            self.assertEqual(question.findtext("name/text"), "QB-MC-002")
            self.assertEqual(question.findtext("single"), "false")
            self.assertEqual(Decimal(question.findtext("defaultgrade")), 2)

            answers = question.findall("answer")
            self.assertEqual(len(answers), 4)
            self.assertEqual(
                {a.findtext("text"): Decimal(a.attrib["fraction"]) for a in answers},
                {"3": -50, "4": 50, "5": -50, "6": 50},
            )


if __name__ == "__main__":
    for path in (CONVERTER, FIXTURE):
        if not path.is_file():
            raise SystemExit(f"ABBRUCH: {path.name} fehlt im Prototyp-Ordner.")

    # Die sieben bisherigen Tests in diesem Lauf gegen v0.4 ausfuehren.
    tests_v02.CONVERTER = CONVERTER
    tests_v03.CONVERTER = CONVERTER

    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite([
        loader.loadTestsFromModule(tests_v02),
        loader.loadTestsFromModule(tests_v03),
        loader.loadTestsFromTestCase(QuestionBridgeV04Tests),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
