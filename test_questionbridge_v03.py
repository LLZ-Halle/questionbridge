from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
CONVERTER = ROOT / "questionbridge_v03.py"
ORIGINAL_ZIP = ROOT / "1795432100__0__qpl_329.zip"
ORIGINAL_QTI = ROOT / "1795432100__0__qti_329.xml"


class QuestionBridgeV03ZipTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.work = Path(temp.name)

    def convert(self, source, destination):
        return subprocess.run(
            [sys.executable, str(CONVERTER), str(source), str(destination)],
            capture_output=True,
            text=True,
        )

    def test_original_zip_matches_qti(self):
        from_zip = self.work / "from-zip.xml"
        from_qti = self.work / "from-qti.xml"

        for source, destination in (
            (ORIGINAL_ZIP, from_zip),
            (ORIGINAL_QTI, from_qti),
        ):
            result = self.convert(source, destination)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        self.assertEqual(from_zip.read_bytes(), from_qti.read_bytes())

    def check_rejected_zip(self, names, count):
        archive_path = self.work / "test.zip"
        output = self.work / "moodle.xml"
        with ZipFile(archive_path, "w") as archive:
            for name in names:
                archive.writestr(name, "<test/>")

        result = self.convert(archive_path, output)
        message = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, message)
        self.assertIn(
            f"Genau eine QTI-XML erwartet, {count} gefunden.",
            message,
        )
        self.assertFalse(output.exists(), "Unerwartete Moodle-XML erzeugt")

    def test_zip_without_qti_is_rejected(self):
        self.check_rejected_zip(["manifest.xml"], 0)

    def test_zip_with_two_qti_files_is_rejected(self):
        self.check_rejected_zip(
            ["pool/1__0__qti_329.xml", "pool/2__0__qti_329.xml"], 2
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
