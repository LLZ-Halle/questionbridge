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
        p = subprocess.run([sys.executable, str(ROOT / 'questionbridge_v016.py'),
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
                [qb_sys.executable, "-B", str(project / "questionbridge_v016.py"),
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
                [qb_sys.executable, "-B", str(project / "questionbridge_v016.py"),
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
                     str(project / "questionbridge_v016.py"),
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
                    [qb_sys.executable, "-B", str(project / "questionbridge_v016.py"),
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
                [qb_sys.executable, "-B", str(project / "questionbridge_v016.py"),
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


class TestMatchingV011(qb_unittest.TestCase):
    SOURCE = "1795691867__0__qti_339.xml"

    def convert(self, source, error=None):
        project = QBPath(__file__).resolve().parent
        with qb_tempfile.TemporaryDirectory() as directory:
            output = QBPath(directory) / "moodle.xml"
            result = qb_subprocess.run(
                [qb_sys.executable, "-B", str(project / "questionbridge_v016.py"),
                 str(source), str(output)],
                capture_output=True, text=True,
            )
            if error:
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(error, result.stderr)
                self.assertFalse(output.exists())
                return None
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return qb_et.parse(output).getroot().findall("question")

    def variant(self, directory, edit):
        project = QBPath(__file__).resolve().parent
        tree = qb_et.parse(project / self.SOURCE)
        edit(tree)
        path = QBPath(directory) / "variant.xml"
        tree.write(path, encoding="utf-8")
        return path

    def test_matching_one_to_one(self):
        project = QBPath(__file__).resolve().parent
        questions = self.convert(project / self.SOURCE)
        self.assertEqual(len(questions), 1)
        q = questions[0]
        self.assertEqual(q.get("type"), "matching")
        self.assertEqual(q.findtext("name/text"), "QB-MATCH-V011-1ZU1")
        self.assertEqual(q.findtext("questiontext/text"), "Ordne zu!")
        self.assertEqual(QBDecimal(q.findtext("defaultgrade")), 6)
        self.assertEqual(q.findtext("shuffleanswers"), "0")
        subs = q.findall("subquestion")
        self.assertEqual(len(subs), 3)
        self.assertEqual(
            {s.findtext("text"): s.findtext("answer/text") for s in subs},
            {"Italy": "Rom", "Japan": "Tokio", "Ottawa": "Kanada"},
        )
        self.assertEqual(len({s.findtext("answer/text") for s in subs}), 3)

    def test_matching_unequal_points_rejected(self):
        def edit(tree):
            tree.findall(".//respcondition/setvar")[0].text = "3"
        with qb_tempfile.TemporaryDirectory() as directory:
            self.convert(self.variant(directory, edit), "ungleiche Punkte")

    def test_matching_n_to_n_rejected(self):
        def edit(tree):
            for f in tree.iter("qtimetadatafield"):
                if f.findtext("fieldlabel") == "matching_mode":
                    f.find("fieldentry").text = "n:n"
        with qb_tempfile.TemporaryDirectory() as directory:
            self.convert(self.variant(directory, edit), "Zuordnungsmodus")


class TestClozeV012(qb_unittest.TestCase):
    SOURCE = "1795697860__0__qti_339.xml"

    def convert(self, source, error=None):
        project = QBPath(__file__).resolve().parent
        with qb_tempfile.TemporaryDirectory() as directory:
            output = QBPath(directory) / "moodle.xml"
            result = qb_subprocess.run(
                [qb_sys.executable, "-B", str(project / "questionbridge_v016.py"),
                 str(source), str(output)],
                capture_output=True, text=True,
            )
            if error:
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(error, result.stderr)
                self.assertFalse(output.exists())
                return None
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return qb_et.parse(output).getroot().findall("question")

    def variant(self, directory, edit):
        project = QBPath(__file__).resolve().parent
        tree = qb_et.parse(project / self.SOURCE)
        edit(tree)
        path = QBPath(directory) / "variant.xml"
        tree.write(path, encoding="utf-8")
        return path

    def rejected(self, edit, error):
        with qb_tempfile.TemporaryDirectory() as directory:
            self.convert(self.variant(directory, edit), error)

    def test_cloze_mixed_gaps(self):
        project = QBPath(__file__).resolve().parent
        questions = self.convert(project / self.SOURCE)
        self.assertEqual(len(questions), 1)
        q = questions[0]
        self.assertEqual(q.get("type"), "cloze")
        self.assertEqual(q.findtext("name/text"), "QB-CLOZE-V012-GEMISCHT")
        self.assertEqual(q.find("questiontext").get("format"), "html")
        self.assertEqual(QBDecimal(q.findtext("defaultgrade")), 6)
        self.assertEqual(
            q.findtext("questiontext/text"),
            "Fülle die Lücken!<br>"
            "Die Hauptstadt von Italien ist {2:SHORTANSWER:=Rom}. "
            "Der Himmel ist bei klarem Wetter {1:MULTICHOICE_S:=blau~grün~rot}. "
            "Wasser siedet bei Normaldruck bei {3:NUMERICAL:=100:2} Grad Celsius.",
        )

    def test_cloze_fractional_points_rejected(self):
        def edit(tree):
            tree.findall(".//respcondition/setvar")[0].text = "1.5"
        self.rejected(edit, "ganzzahlig")

    def test_cloze_asymmetric_range_rejected(self):
        def edit(tree):
            for node in tree.iter("render_fib"):
                if node.get("maxnumber"):
                    node.set("maxnumber", "105")
        self.rejected(edit, "symmetrischen")

    def test_cloze_text_rating_rejected(self):
        def edit(tree):
            for f in tree.iter("qtimetadatafield"):
                if f.findtext("fieldlabel") == "textgaprating":
                    f.find("fieldentry").text = "l1"
        self.rejected(edit, "Textluecken-Bewertung")

    def test_cloze_special_character_rejected(self):
        def edit(tree):
            for v in tree.iter("varequal"):
                if v.get("respident") == "gap_0":
                    v.text = "R~m"
        self.rejected(edit, "Sonderzeichen")


class TestEssayV013(qb_unittest.TestCase):
    SOURCE = "1795699061__0__qti_339.xml"

    def convert(self, source, error=None):
        project = QBPath(__file__).resolve().parent
        with qb_tempfile.TemporaryDirectory() as directory:
            output = QBPath(directory) / "moodle.xml"
            result = qb_subprocess.run(
                [qb_sys.executable, "-B", str(project / "questionbridge_v016.py"),
                 str(source), str(output)],
                capture_output=True, text=True,
            )
            if error:
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(error, result.stderr)
                self.assertFalse(output.exists())
                return None
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return qb_et.parse(output).getroot().findall("question")

    def rejected(self, edit, error):
        project = QBPath(__file__).resolve().parent
        with qb_tempfile.TemporaryDirectory() as directory:
            tree = qb_et.parse(project / self.SOURCE)
            edit(tree)
            path = QBPath(directory) / "variant.xml"
            tree.write(path, encoding="utf-8")
            self.convert(path, error)

    def test_essay_reference(self):
        project = QBPath(__file__).resolve().parent
        questions = self.convert(project / self.SOURCE)
        self.assertEqual(len(questions), 1)
        q = questions[0]
        self.assertEqual(q.get("type"), "essay")
        self.assertEqual(q.findtext("name/text"), "QB-ESSAY-V013-REFERENZ")
        self.assertEqual(q.findtext("questiontext/text"),
                         "Beschreibe in drei Sätzen den Unterschied zwischen SC und MC.")
        self.assertEqual(QBDecimal(q.findtext("defaultgrade")), 10)
        self.assertEqual(q.findtext("responseformat"), "plain")
        self.assertEqual(q.findtext("attachments"), "0")

    def test_essay_word_counter_rejected(self):
        def edit(tree):
            for f in tree.iter("qtimetadatafield"):
                if f.findtext("fieldlabel") == "wordcounter":
                    f.find("fieldentry").text = "1"
        self.rejected(edit, "Wortzaehler")

    def test_essay_keyword_scoring_rejected(self):
        def edit(tree):
            for f in tree.iter("qtimetadatafield"):
                if f.findtext("fieldlabel") == "termrelation":
                    f.find("fieldentry").text = "any"
        self.rejected(edit, "Stichwortbewertung")

    def test_essay_automatic_scoring_rejected(self):
        def edit(tree):
            for node in tree.iter("resprocessing"):
                node.set("scoremodel", "Automatic")
        self.rejected(edit, "manuelle Bewertung")


import base64


class TestKeywordV014(qb_unittest.TestCase):
    SOURCE = "1795700896__0__qti_341.xml"

    def convert(self, source, error=None):
        project = QBPath(__file__).resolve().parent
        with qb_tempfile.TemporaryDirectory() as directory:
            output = QBPath(directory) / "moodle.xml"
            result = qb_subprocess.run(
                [qb_sys.executable, "-B", str(project / "questionbridge_v016.py"),
                 str(source), str(output)],
                capture_output=True, text=True,
            )
            if error:
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(error, result.stderr)
                self.assertFalse(output.exists())
                return None
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return qb_et.parse(output).getroot().findall("question")

    def rejected(self, edit, error):
        project = QBPath(__file__).resolve().parent
        with qb_tempfile.TemporaryDirectory() as directory:
            tree = qb_et.parse(project / self.SOURCE)
            edit(tree)
            path = QBPath(directory) / "variant.xml"
            tree.write(path, encoding="utf-8")
            self.convert(path, error)

    @staticmethod
    def encode(terms):
        body = "".join(
            'i:%d;O:31:"ASS_AnswerMultipleResponseImage":6:{'
            's:13:"\x00*\x00answertext";s:%d:"%s";'
            's:9:"\x00*\x00points";s:%d:"%s";'
            's:8:"\x00*\x00order";i:0;s:5:"\x00*\x00id";i:-1;'
            's:16:"points_unchecked";N;s:5:"image";N;}'
            % (i, len(t.encode()), t, len(str(p)), p)
            for i, (t, p) in enumerate(terms)
        )
        raw = "a:%d:{%s}" % (len(terms), body)
        return base64.b64encode(raw.encode()).decode()

    def set_field(self, tree, title, label, value):
        for item in tree.iter("item"):
            if item.get("title") == title:
                for f in item.iter("qtimetadatafield"):
                    if f.findtext("fieldlabel") == label:
                        f.find("fieldentry").text = value
                        return
        raise AssertionError((title, label))

    def test_encoder_matches_export(self):
        project = QBPath(__file__).resolve().parent
        tree = qb_et.parse(project / self.SOURCE)
        fields = {
            item.get("title"): {f.findtext("fieldlabel"): f.findtext("fieldentry")
                                for f in item.iter("qtimetadatafield")}
            for item in tree.iter("item")
        }
        self.assertEqual(self.encode([("Tiger", 0), ("Wal", 0)]),
                         fields["QB-TEXT-V014-EINES"]["termscoring"])
        self.assertEqual(self.encode([("Tiger", 2), ("Wal", 2)]),
                         fields["QB-TEXT-V014-EINZELN"]["termscoring"])

    def test_keyword_modes(self):
        project = QBPath(__file__).resolve().parent
        questions = self.convert(project / self.SOURCE)
        self.assertEqual(len(questions), 3)
        got, texts = {}, {}
        for q in questions:
            self.assertEqual(q.get("type"), "shortanswer")
            self.assertEqual(QBDecimal(q.findtext("defaultgrade")), 4)
            self.assertEqual(q.findtext("usecase"), "0")
            name = q.findtext("name/text")
            texts[name] = q.findtext("questiontext/text")
            got[name] = [(a.findtext("text"), a.get("fraction")) for a in q.findall("answer")]
        self.assertEqual(texts["QB-TEXT-V014-EINES"], "Nenne ein Säugetier.")
        self.assertEqual(got, {
            "QB-TEXT-V014-EINES": [("*Tiger*", "100"), ("*Wal*", "100")],
            "QB-TEXT-V014-ALLE": [("*Tiger*Wal*", "100"), ("*Wal*Tiger*", "100")],
            "QB-TEXT-V014-EINZELN": [("*Tiger*Wal*", "100"), ("*Wal*Tiger*", "100"),
                                     ("*Tiger*", "50"), ("*Wal*", "50")],
        })

    def test_keyword_text_rating_rejected(self):
        def edit(tree):
            self.set_field(tree, "QB-TEXT-V014-EINES", "textrating", "l1")
        self.rejected(edit, "Textvergleich")

    def test_keyword_three_terms_rejected(self):
        def edit(tree):
            self.set_field(tree, "QB-TEXT-V014-ALLE", "termscoring",
                           self.encode([("Tiger", 0), ("Wal", 0), ("Hai", 0)]))
        self.rejected(edit, "genau zwei")

    def test_keyword_wildcard_character_rejected(self):
        def edit(tree):
            self.set_field(tree, "QB-TEXT-V014-EINES", "termscoring",
                           self.encode([("Ti*ger", 0), ("Wal", 0)]))
        self.rejected(edit, "Sonderzeichen")

    def test_keyword_overlapping_terms_rejected(self):
        def edit(tree):
            self.set_field(tree, "QB-TEXT-V014-ALLE", "termscoring",
                           self.encode([("Tiger", 0), ("iger", 0)]))
        self.rejected(edit, "ueberlappen")


import re as qb_re
import zipfile as qb_zipfile


class TestMixedPoolV014(qb_unittest.TestCase):
    SOURCES = [
        "1795182081__0__qti_329.xml",
        "1795425389__0__qti_329.xml",
        "1795687994__0__qpl_339.zip",
        "1795691867__0__qti_339.xml",
        "1795697860__0__qti_339.xml",
        "1795699061__0__qti_339.xml",
        "1795700896__0__qti_341.xml",
        "1795702712__0__qti_339.xml",
        "1795707402__0__qti_339.xml",
    ]
    TYPES = ["multichoice", "multichoice", "numerical", "matching", "cloze",
             "essay", "shortanswer", "shortanswer", "shortanswer", "kprime", "cloze"]

    def qti_bytes(self, path):
        if path.suffix != ".zip":
            return path.read_bytes()
        with qb_zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist()
                     if qb_re.fullmatch(r".+__qti_.+\.xml", n.rsplit("/", 1)[-1])]
            self.assertEqual(len(names), 1, names)
            return archive.read(names[0])

    def convert(self, source, destination):
        project = QBPath(__file__).resolve().parent
        result = qb_subprocess.run(
            [qb_sys.executable, "-B", str(project / "questionbridge_v016.py"),
             str(source), str(destination)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        questions = qb_et.parse(destination).getroot().findall("question")
        for q in questions:
            q.tail = None
        return questions

    def test_all_types_in_one_pool_match_single_conversions(self):
        project = QBPath(__file__).resolve().parent
        with qb_tempfile.TemporaryDirectory() as directory:
            folder = QBPath(directory)
            root = qb_et.Element("questestinterop")
            expected = []
            for index, name in enumerate(self.SOURCES):
                source = project / name
                root.extend(qb_et.fromstring(self.qti_bytes(source)).iter("item"))
                expected += self.convert(source, folder / f"single-{index}.xml")
            merged = folder / "pool.qti.xml"
            qb_et.ElementTree(root).write(merged, encoding="utf-8", xml_declaration=True)
            actual = self.convert(merged, folder / "pool.moodle.xml")

        self.assertEqual([q.get("type") for q in actual], self.TYPES)
        self.assertEqual([qb_et.tostring(q) for q in actual],
                         [qb_et.tostring(q) for q in expected])


class TestKprimV015(qb_unittest.TestCase):
    SOURCE = "1795702712__0__qti_339.xml"

    def project(self):
        return QBPath(__file__).resolve().parent

    def reference(self):
        for pattern in ("moodle-kprime-reference.xml", "questions-KFS-Selected*1458.xml"):
            found = sorted(self.project().glob(pattern))
            if found:
                return qb_et.parse(found[0]).getroot().findall("question")[0]
        raise AssertionError("Moodle-Kprime-Referenz nicht gefunden.")

    def convert(self, source, error=None):
        with qb_tempfile.TemporaryDirectory() as directory:
            output = QBPath(directory) / "moodle.xml"
            result = qb_subprocess.run(
                [qb_sys.executable, "-B", str(self.project() / "questionbridge_v016.py"),
                 str(source), str(output)],
                capture_output=True, text=True,
            )
            if error:
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(error, result.stderr)
                self.assertFalse(output.exists())
                return None
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return qb_et.parse(output).getroot().findall("question")

    def variant(self, edit, error=None):
        with qb_tempfile.TemporaryDirectory() as directory:
            tree = qb_et.parse(self.project() / self.SOURCE)
            edit(tree)
            path = QBPath(directory) / "variant.xml"
            tree.write(path, encoding="utf-8")
            return self.convert(path, error)

    @staticmethod
    def weights(question):
        return {(int(w.get("rownumber")), int(w.get("columnnumber"))):
                QBDecimal(w.findtext("value").strip())
                for w in question.findall("weight")}

    @staticmethod
    def rows(question):
        import html as qb_html
        import re as qb_re2
        return [qb_html.unescape(qb_re2.sub(r"<[^>]+>", "", r.findtext("optiontext/text")))
                for r in question.findall("row")]

    @staticmethod
    def set_meta(tree, label, value):
        for f in tree.iter("qtimetadatafield"):
            if f.findtext("fieldlabel") == label:
                f.find("fieldentry").text = value
                return
        raise AssertionError(label)

    def test_kprim_matches_moodle_reference(self):
        questions = self.convert(self.project() / self.SOURCE)
        self.assertEqual(len(questions), 1)
        q, ref = questions[0], self.reference()
        self.assertEqual(q.get("type"), "kprime")
        self.assertEqual(q.findtext("name/text"), "Titel QB-KPRIM-V015-REFERENZ")
        self.assertEqual(q.findtext("questiontext/text"), "<p>Richtig oder falsch?</p>")
        for tag in ("defaultgrade", "numberofrows", "numberofcolumns", "shuffleanswers"):
            self.assertEqual(q.findtext(tag).strip(), ref.findtext(tag).strip(), tag)
        self.assertEqual(q.findtext("scoringmethod/text").strip(),
                         ref.findtext("scoringmethod/text").strip())
        self.assertEqual(self.rows(q), self.rows(ref))
        self.assertEqual(self.rows(q), ["blau", "grün", "rot", "gelb"])
        self.assertEqual(self.weights(q), self.weights(ref))
        self.assertEqual([c.findtext("responsetext/text") for c in q.findall("column")],
                         ["Richtig", "Falsch"])

    def test_kprim_truth_is_read_from_values(self):
        def edit(tree):
            for node in tree.iter("varequal"):
                node.text = "1" if node.text.strip() == "0" else "0"
        q, = self.variant(edit)
        self.assertEqual([self.weights(q)[(n, 1)] for n in (1, 2, 3, 4)], [1, 0, 1, 0])
        self.assertEqual([self.weights(q)[(n, 2)] for n in (1, 2, 3, 4)], [0, 1, 0, 1])

    def test_kprim_points_follow_scoring_rule(self):
        def edit(tree):
            for rule in tree.iter("respcondition"):
                if rule.find("conditionvar/and") is not None:
                    rule.find("setvar").text = "6"
            tree.find(".//decvar").set("maxvalue", "6")
        q, = self.variant(edit)
        self.assertEqual(QBDecimal(q.findtext("defaultgrade")), 6)

    def test_kprim_partial_credit_rejected(self):
        def edit(tree):
            for rule in tree.iter("respcondition"):
                if rule.find("conditionvar/or") is not None:
                    rule.find("setvar").text = "1"
        self.variant(edit, "alles-oder-nichts")

    def test_kprim_inconsistent_solution_rejected(self):
        def edit(tree):
            node = tree.findall("./item/resprocessing/respcondition/conditionvar/varequal")[0]
            node.text = "1" if node.text.strip() == "0" else "0"
        self.variant(edit, "widerspruechlich")

    def test_kprim_maximum_mismatch_rejected(self):
        def edit(tree):
            tree.find(".//decvar").set("maxvalue", "5")
        self.variant(edit, "Maximalpunktzahl")

    def test_kprim_custom_labels_rejected(self):
        self.variant(lambda t: self.set_meta(t, "option_label_setting", "custom"),
                     "Kprim-Beschriftung")

    def test_kprim_answer_type_rejected(self):
        self.variant(lambda t: self.set_meta(t, "answer_type", "multiLine"),
                     "Kprim-Antworttyp")

    def test_kprim_feedback_rejected(self):
        def edit(tree):
            tree.find(".//itemfeedback//mattext").text = "Hallo"
        self.variant(edit, "Feedback bei Kprim")


class TestLongMenuV016(qb_unittest.TestCase):
    SOURCE = "1795707402__0__qti_339.xml"
    TEXT = ("Was sind die Hauptstädte? <br>Die Hauptstadt von Italien ist "
            "{2:MULTICHOICE:Mailand~Neapel~=Rom~Turin}. Die Hauptstadt von Japan ist "
            "{3:SHORTANSWER_C:=Tokio}.")

    def project(self):
        return QBPath(__file__).resolve().parent

    def convert(self, source, error=None):
        with qb_tempfile.TemporaryDirectory() as directory:
            output = QBPath(directory) / "moodle.xml"
            result = qb_subprocess.run(
                [qb_sys.executable, "-B", str(self.project() / "questionbridge_v016.py"),
                 str(source), str(output)],
                capture_output=True, text=True,
            )
            if error:
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(error, result.stderr)
                self.assertFalse(output.exists())
                return None
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return qb_et.parse(output).getroot().findall("question")

    def variant(self, edit, error=None):
        with qb_tempfile.TemporaryDirectory() as directory:
            tree = qb_et.parse(self.project() / self.SOURCE)
            edit(tree)
            path = QBPath(directory) / "variant.xml"
            tree.write(path, encoding="utf-8")
            return self.convert(path, error)

    @staticmethod
    def score(tree, gap, option, value):
        for rule in tree.iter("respcondition"):
            node = rule.find("conditionvar/varequal")
            if node.get("respident") == gap and node.text == option:
                rule.find("setvar").text = str(value)
                return
        raise AssertionError((gap, option))

    @staticmethod
    def meta(tree, label, value):
        for f in tree.iter("qtimetadatafield"):
            if f.findtext("fieldlabel") == label:
                f.find("fieldentry").text = value
                return
        raise AssertionError(label)

    def test_longmenu_reference(self):
        q, = self.convert(self.project() / self.SOURCE)
        self.assertEqual(q.get("type"), "cloze")
        self.assertEqual(q.findtext("name/text"), "QB-LONGMENU-V016-REFERENZ")
        self.assertEqual(q.find("questiontext").get("format"), "html")
        self.assertEqual(QBDecimal(q.findtext("defaultgrade")), 5)
        self.assertEqual(q.findtext("questiontext/text"), self.TEXT)

    def test_longmenu_points_from_values(self):
        def edit(tree):
            self.score(tree, "LongMenu_1", "Rom", 4)
            self.score(tree, "LongMenu_2", "Tokio", 2)
        q, = self.variant(edit)
        self.assertEqual(QBDecimal(q.findtext("defaultgrade")), 6)
        text = q.findtext("questiontext/text")
        self.assertIn("{4:MULTICHOICE:", text)
        self.assertIn("{2:SHORTANSWER_C:", text)

    def test_longmenu_correct_answer_from_values(self):
        def edit(tree):
            self.score(tree, "LongMenu_1", "Rom", 0)
            self.score(tree, "LongMenu_1", "Neapel", 2)
        q, = self.variant(edit)
        self.assertIn("{2:MULTICHOICE:Mailand~=Neapel~Rom~Turin}",
                      q.findtext("questiontext/text"))

    def test_longmenu_text_gap_accepts_several_correct_answers(self):
        q, = self.variant(lambda t: self.score(t, "LongMenu_2", "Kyoto", 3))
        self.assertIn("{3:SHORTANSWER_C:=Kyoto~=Tokio}", q.findtext("questiontext/text"))

    def test_longmenu_two_correct_in_select_rejected(self):
        self.variant(lambda t: self.score(t, "LongMenu_1", "Mailand", 2),
                     "genau eine richtige")

    def test_longmenu_unequal_points_rejected(self):
        self.variant(lambda t: self.score(t, "LongMenu_2", "Kyoto", 1), "ungleiche Punkte")

    def test_longmenu_no_correct_answer_rejected(self):
        self.variant(lambda t: self.score(t, "LongMenu_2", "Tokio", 0), "keine richtige")

    def test_longmenu_fractional_points_rejected(self):
        self.variant(lambda t: self.score(t, "LongMenu_1", "Rom", "1.5"), "ganzzahlig")

    def test_longmenu_unknown_gap_type_rejected(self):
        self.variant(lambda t: self.meta(t, "gapTypes", "[0,2]"), "Long-Menu-Lueckentyp")

    def test_longmenu_identical_scoring_rejected(self):
        self.variant(lambda t: self.meta(t, "identical_scoring", "1"), "Identische Bewertung")

    def test_longmenu_feedback_rejected(self):
        def edit(tree):
            tree.find(".//itemfeedback//mattext").text = "Hallo"
        self.variant(edit, "Feedback bei Long Menu")

    def test_longmenu_missing_placeholder_rejected(self):
        def edit(tree):
            node = tree.findall(".//presentation/flow/material/mattext")[1]
            node.text = node.text.replace("[Longmenu 2]", "X")
        self.variant(edit, "Platzhalter")

    def test_longmenu_special_character_rejected(self):
        def edit(tree):
            for node in tree.iter("fieldentry"):
                if node.text == "Mailand":
                    node.text = "Mai~land"
            for node in tree.iter("varequal"):
                if node.text == "Mailand":
                    node.text = "Mai~land"
        self.variant(edit, "Sonderzeichen")


if __name__ == "__main__":
    qb_unittest.main(verbosity=2)
