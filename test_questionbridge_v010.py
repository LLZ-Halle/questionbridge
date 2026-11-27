import subprocess
import sys
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SC = '1795182081__0__qti_329.xml'
MC = '1795425389__0__qti_329.xml'
POOL = '1795432100__0__qti_329.xml'

class QuestionBridgeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def run_converter(self, source, error=None):
        dest = self.tmp / 'out.xml'
        dest.unlink(missing_ok=True)
        p = subprocess.run([sys.executable, str(ROOT / 'questionbridge_v010.py'),
                            str(source), str(dest)], capture_output=True, text=True)
        if error:
            self.assertNotEqual(p.returncode, 0)
            self.assertIn(error, p.stderr)
            self.assertFalse(dest.exists())
            return
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return dest.read_bytes()

    def check(self, data, title, single, points, weights):
        q, = ET.fromstring(data).findall('question')
        self.assertEqual(q.get('type'), 'multichoice')
        self.assertEqual(q.findtext('name/text'), title)
        self.assertEqual(q.findtext('single'), str(single).lower())
        self.assertEqual(Decimal(q.findtext('defaultgrade')), Decimal(str(points)))
        answers = q.findall('answer')
        self.assertEqual(len(answers), len(weights))
        self.assertEqual([Decimal(a.get('fraction')) for a in answers],
                         [Decimal(str(w)) for w in weights])

    def test_sc(self):
        self.check(self.run_converter(ROOT / SC), 'QB-SC-001', True, 1, [0,100,0])

    def test_mc(self):
        self.check(self.run_converter(ROOT / MC), 'QB-MC-001', False, 2, [0,50,0,50])

    def test_pool(self):
        actual = list(ET.fromstring(self.run_converter(ROOT / POOL)))
        expected = [ET.fromstring(self.run_converter(ROOT / f))[0] for f in (SC, MC)]
        for q in actual + expected:
            q.tail = None
        self.assertEqual([ET.tostring(q) for q in actual], [ET.tostring(q) for q in expected])

    def test_missing_input(self):
        self.run_converter(self.tmp / 'missing.xml', 'ABBRUCH:')

    def zip_case(self, n):
        archive = self.tmp / 'input.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            for i in range(n):
                z.write(ROOT / POOL, f'{i}/{POOL}')
        return archive

    def test_zip_one(self):
        self.assertEqual(self.run_converter(self.zip_case(1)), self.run_converter(ROOT / POOL))

    def test_zip_zero(self):
        self.run_converter(self.zip_case(0), '0 gefunden')

    def test_zip_two(self):
        self.run_converter(self.zip_case(2), '2 gefunden')

    def test_mc002(self):
        self.check(self.run_converter(ROOT / '1795438654__0__qti_329.xml'), 'QB-MC-002', False, 2, [-50,50,-50,50])

    def test_mc003(self):
        self.check(self.run_converter(ROOT / '1795440234__0__qti_329.xml'), 'QB-MC-003', False, 4, [-25,25,-25,75])

    def test_mc004(self):
        self.check(self.run_converter(ROOT / '1795443466__0__qti_329.xml'), 'QB-MC-004', False, 4, [25,25,-25,50])

    def fixture(self, filename, scores, unselected=0):
        tree = ET.parse(ROOT / filename)
        selected = [c.find('setvar') for c in tree.findall('.//respcondition')
                    if c.find('conditionvar/varequal') is not None]
        self.assertEqual(len(selected), len(scores))
        for node, score in zip(selected, scores):
            node.text = str(score)
        if unselected:
            tree.find('.//conditionvar/not/../..//setvar').text = str(unselected)
        path = self.tmp / 'synthetic.xml'
        tree.write(path, encoding='utf-8')
        return path

    def test_sc_partial_and_negative(self):
        p = self.fixture(SC, [1, 4, -1])
        self.check(self.run_converter(p), 'QB-SC-001', True, 4, [25,100,-25])

    def test_sc_tied_full_credit(self):
        p = self.fixture(SC, [2, 2, 0])
        self.check(self.run_converter(p), 'QB-SC-001', True, 2, [100,100,0])

    def test_mc_one_positive(self):
        p = self.fixture(MC, [0, 2, -1, 0])
        self.check(self.run_converter(p), 'QB-MC-001', False, 2, [0,100,-50,0])

    def test_mc_new_weights(self):
        p = self.fixture(MC, [-1, 1, -1, 4])
        self.check(self.run_converter(p), 'QB-MC-001', False, 5, [-20,20,-20,80])

    def test_mc_decimal_weights(self):
        p = self.fixture(MC, [-0.125, 0.125, 0.125, 0.75])
        self.check(self.run_converter(p), 'QB-MC-001', False, 1, [-12.5,12.5,12.5,75])

    def test_unlisted_weight_rejected(self):
        self.run_converter(self.fixture(MC, [0, 3, 0, 5]), 'nicht exakt')

    def test_periodic_weight_rejected(self):
        self.run_converter(self.fixture(MC, [0, 1, 0, 2]), 'nicht exakt')

    def test_nonzero_unselected_rejected(self):
        self.run_converter(self.fixture(MC, [0, 1, 0, 1], 1), 'Nichtauswahl')

    def test_no_positive_rejected(self):
        self.run_converter(self.fixture(MC, [0, -1, 0, 0]), 'positive Antwort')

if __name__ == '__main__':
    unittest.main(verbosity=2)


import subprocess as qb_subprocess
import sys as qb_sys
import tempfile as qb_tempfile
import unittest as qb_unittest
import xml.etree.ElementTree as qb_et
from decimal import Decimal as QBDecimal
from pathlib import Path as QBPath


class TestAnswerFeedbackV08(qb_unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        project = QBPath(__file__).resolve().parent
        fixture = project / "1795448372__0__qti_329.xml"
        with qb_tempfile.TemporaryDirectory() as directory:
            output = QBPath(directory) / "moodle-feedback.xml"
            result = qb_subprocess.run(
                [qb_sys.executable, "-B", str(project / "questionbridge_v010.py"),
                 str(fixture), str(output)],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise AssertionError(
                    f"Konvertierung fehlgeschlagen:\n{result.stdout}\n{result.stderr}"
                )
            cls.questions = qb_et.parse(output).getroot().findall("question")

    def check_question(self, single, max_points, expected):
        matches = [q for q in self.questions if q.findtext("single") == single]
        self.assertEqual(len(matches), 1)
        question = matches[0]
        self.assertEqual(QBDecimal(question.findtext("defaultgrade")), max_points)

        actual = {}
        for answer in question.findall("answer"):
            label = answer.findtext("text")
            self.assertNotIn(label, actual)
            feedback = answer.findall("feedback")
            text = None
            if feedback:
                self.assertEqual(len(feedback), 1)
                self.assertEqual(feedback[0].get("format"), "plain_text")
                text = feedback[0].findtext("text", "")
                self.assertTrue(text.strip(), f"Leeres Feedback für Antwort {label}")
            actual[label] = (QBDecimal(answer.get("fraction")), text)
        self.assertEqual(actual, expected)

    def test_sc_feedback_and_weights(self):
        self.check_question("true", 4, {
            "2": (25, "Teilpunkte"),
            "3": (-25, "falsche Antwort"),
            "4": (100, "volle Punktzahl"),
        })

    def test_mc_feedback_weights_and_omitted_empty_feedback(self):
        self.check_question("false", 5, {
            "2": (20, None),
            "3": (-20, "zieht einen Punkt ab"),
            "5": (-20, None),
            "6": (80, "gibt vier Punkte"),
        })


class TestNumericalV010(qb_unittest.TestCase):
    def test_numeric_inclusive_range_from_ilias_zip(self):
        project = QBPath(__file__).resolve().parent
        source = project / "1795687994__0__qpl_339.zip"

        with qb_tempfile.TemporaryDirectory() as directory:
            output = QBPath(directory) / "moodle.xml"
            result = qb_subprocess.run(
                [qb_sys.executable, "-B", str(project / "questionbridge_v010.py"),
                 str(source), str(output)],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            questions = qb_et.parse(output).getroot().findall("question")

        self.assertEqual(len(questions), 1)
        question = questions[0]
        self.assertEqual(question.get("type"), "numerical")
        self.assertEqual(question.findtext("name/text"), "QB-NUM-V010-BEREICH")
        self.assertEqual(question.findtext("questiontext/text"), "Gib eine Zahl ein!")
        self.assertEqual(QBDecimal(question.findtext("defaultgrade")), 5)
        answers = question.findall("answer")
        self.assertEqual(len(answers), 1)
        answer = answers[0]
        self.assertEqual(QBDecimal(answer.get("fraction")), 100)
        self.assertEqual(QBDecimal(answer.findtext("text")), 30)
        self.assertEqual(QBDecimal(answer.findtext("tolerance")), 2)
        self.assertFalse(question.findall("unit"))
        self.assertIsNone(answer.find("feedback"))


class TestResultFeedbackV09(qb_unittest.TestCase):

    def test_mixed_pool_keeps_result_feedback_and_answer_weights(self):
        project = QBPath(__file__).resolve().parent
        cases = {
            "QB-SC-V09-FEEDBACK": (
                "1795450614__0__qti_329.xml", "true", 4,
                "Rückmeldung bei richtiger Lösung",
                "Rückmeldung bei nicht vollständig richtiger Lösung",
            ),
            "QB-MC-V09-FEEDBACK": (
                "1795614602__0__qti_329.xml", "false", 5,
                "MC-V09: vollständig richtig",
                "MC-V09: nicht vollständig richtig",
            ),
        }

        def answers(question):
            return [
                (a.findtext("text"), QBDecimal(a.get("fraction")),
                 a.findtext("feedback/text"))
                for a in question.findall("answer")
            ]

        with qb_tempfile.TemporaryDirectory() as directory:
            folder = QBPath(directory)

            def convert(filename):
                output = folder / (filename + ".moodle.xml")
                result = qb_subprocess.run(
                    [qb_sys.executable, "-B",
                     str(project / "questionbridge_v010.py"),
                     str(project / filename), str(output)],
                    capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return qb_et.parse(output).getroot().findall("question")

            pool = convert("1795685972__0__qpl_339.zip")
            self.assertCountEqual([q.findtext("name/text") for q in pool], cases.keys())

            for question in pool:
                title = question.findtext("name/text")
                with self.subTest(question=title):
                    filename, single, grade, correct, incomplete = cases[title]
                    self.assertEqual(question.get("type"), "multichoice")
                    self.assertEqual(question.findtext("single"), single)
                    self.assertEqual(QBDecimal(question.findtext("defaultgrade")), grade)

                    for tag, expected in (
                        ("correctfeedback", correct),
                        ("partiallycorrectfeedback", incomplete),
                        ("incorrectfeedback", incomplete),
                    ):
                        fields = question.findall(tag)
                        self.assertEqual(len(fields), 1, tag)
                        self.assertEqual(fields[0].get("format"), "plain_text", tag)
                        self.assertEqual(fields[0].findtext("text"), expected, tag)

                    reference = convert(filename)
                    self.assertEqual(len(reference), 1)
                    self.assertEqual(reference[0].findtext("name/text"), title)
                    self.assertCountEqual(answers(question), answers(reference[0]))

    def test_mc_result_feedback_keeps_answer_feedback_and_weights(self):
        project = QBPath(__file__).resolve().parent
        source = project / "1795614602__0__qti_329.xml"
        refs = {"response_allcorrect", "response_onenotcorrect"}

        with qb_tempfile.TemporaryDirectory() as directory:
            folder = QBPath(directory)

            def convert(input_path, filename):
                output = folder / filename
                result = qb_subprocess.run(
                    [qb_sys.executable, "-B", str(project / "questionbridge_v010.py"),
                     str(input_path), str(output)],
                    capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                questions = qb_et.parse(output).getroot().findall("question")
                self.assertEqual(len(questions), 1)
                return questions[0]

            question = convert(source, "with-result-feedback.xml")

            # Kontrollversion: Nur die beiden Ergebnisfeedbackregeln und -texte
            # entfernen. Bewertungsregeln und Antwortfeedback bleiben erhalten.
            tree = qb_et.parse(source)
            baseline = folder / "without-result-feedback.qti.xml"
            for item in tree.getroot().iter("item"):
                for processing in item.findall("resprocessing"):
                    for rule in processing.findall("respcondition"):
                        if any(link.get("linkrefid") in refs
                               for link in rule.findall("displayfeedback")):
                            self.assertFalse(rule.findall("setvar"))
                            processing.remove(rule)
                for entry in item.findall("itemfeedback"):
                    if entry.get("ident") in refs:
                        item.remove(entry)
            tree.write(baseline, encoding="utf-8", xml_declaration=True)
            control = convert(baseline, "without-result-feedback.xml")

        self.assertEqual(question.findtext("single"), "false")
        self.assertEqual(QBDecimal(question.findtext("defaultgrade")), 5)
        self.assertEqual(len(question.findall("answer")), 4)
        self.assertIsNone(question.find("generalfeedback"))

        incomplete = "MC-V09: nicht vollständig richtig"
        for tag, expected in (
            ("correctfeedback", "MC-V09: vollständig richtig"),
            ("partiallycorrectfeedback", incomplete),
            ("incorrectfeedback", incomplete),
        ):
            fields = question.findall(tag)
            self.assertEqual(len(fields), 1, tag)
            self.assertEqual(fields[0].get("format"), "plain_text", tag)
            self.assertEqual(fields[0].findtext("text"), expected, tag)
            question.remove(fields[0])

        # Nach Abzug der drei Felder muss die komplette Frage gleich sein,
        # insbesondere Maximalpunktzahl, Antwortgewichte und Antwortfeedback.
        self.assertEqual(qb_et.tostring(question), qb_et.tostring(control))

    def test_sc_result_feedback_keeps_answer_feedback_and_weights(self):
        project = QBPath(__file__).resolve().parent
        source = project / "1795450614__0__qti_329.xml"
        with qb_tempfile.TemporaryDirectory() as directory:
            output = QBPath(directory) / "moodle.xml"
            result = qb_subprocess.run(
                [qb_sys.executable, "-B", str(project / "questionbridge_v010.py"),
                 str(source), str(output)],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            questions = qb_et.parse(output).getroot().findall("question")

        self.assertEqual(len(questions), 1)
        question = questions[0]
        self.assertEqual(question.findtext("name/text"), "QB-SC-V09-FEEDBACK")
        self.assertEqual(question.findtext("single"), "true")
        self.assertEqual(QBDecimal(question.findtext("defaultgrade")), 4)
        incomplete = "Rückmeldung bei nicht vollständig richtiger Lösung"
        for tag, expected in (
            ("correctfeedback", "Rückmeldung bei richtiger Lösung"),
            ("partiallycorrectfeedback", incomplete),
            ("incorrectfeedback", incomplete),
        ):
            fields = question.findall(tag)
            self.assertEqual(len(fields), 1, tag)
            self.assertEqual(fields[0].get("format"), "plain_text", tag)
            self.assertEqual(fields[0].findtext("text"), expected, tag)
        self.assertIsNone(question.find("generalfeedback"))

        answers = question.findall("answer")
        self.assertEqual(len(answers), 3)
        self.assertEqual({
            a.findtext("text"): (
                QBDecimal(a.get("fraction")), a.findtext("feedback/text")
            )
            for a in answers
        }, {
            "2": (25, "Teilpunkte"),
            "3": (-25, "falsche Antwort"),
            "4": (100, "volle Punktzahl"),
        })
