#!/usr/bin/env python3
# Erzeugt questionbridge_v017.py und test_questionbridge_v017.py aus den v016-Dateien.
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent


def replace_once(text, old, new, label):
    if text.count(old) != 1:
        sys.exit(f"Anker nicht eindeutig gefunden ({text.count(old)}x): {label}")
    return text.replace(old, new)


CONVERTER_BLOCK = r"""@dataclass
class OrderingQuestion:
    title: str
    text: str
    items: list
    points: Decimal


def read_ordering_question(item, title, meta):
    error = f"{title}: Nicht unterstuetzte Anordnungsstruktur."
    number = r"[0-9]{1,6}(?:[.][0-9]{1,3})?"
    points_text = (meta.get("points") or "").strip()
    require(re.fullmatch(number, points_text) and Decimal(points_text) > 0,
            f"{title}: Ungueltige Punktzahl bei Anordnungsfrage.")
    points = Decimal(points_text)

    presentation = item.find("presentation")
    require(presentation is not None and len(presentation) == 1, error)
    flow = presentation.find("flow")
    require(flow is not None and [c.tag for c in flow] == ["material", "response_lid"], error)
    material, group = flow
    nodes = material.findall("mattext")
    require(len(material) == 1 and len(nodes) == 1, error)
    prompt = plain(nodes[0])
    require(group.attrib == {"ident": "OQT", "rcardinality": "Ordered",
                             "output": "javascript"} and len(group) == 1, error)
    render = group.find("render_choice")
    require(render is not None and set(render.attrib) <= {"shuffle"}, error)
    require(render.get("shuffle") == "Yes",
            f"{title}: Mischen der Elemente muss aktiv sein (Moodle mischt immer).")
    labels = render.findall("response_label")
    require(len(labels) == len(render) and len(labels) >= 2,
            f"{title}: Mindestens zwei Elemente erforderlich.")
    items = []
    for label in labels:
        require(set(label.attrib) == {"ident"} and [c.tag for c in label] == ["material", "material"],
                error)
        first, second = label
        require(len(first) == 1 and first[0].tag == "material" and len(first[0]) == 1
                and first[0][0].tag == "mattext", error)
        text = plain(first[0][0])
        require(text.strip(), f"{title}: Leeres Element in der Anordnungsfrage.")
        require(len(second) == 1 and second[0].tag == "mattext"
                and second[0].attrib == {"label": "answerdepth"}
                and (second[0].text or "").strip() == "0",
                f"{title}: Verschachtelte Anordnung wird nicht unterstuetzt.")
        items.append(text)
    require(len(set(items)) == len(items), f"{title}: Doppelte Elemente werden nicht unterstuetzt.")

    blocks = item.findall("resprocessing")
    require(len(blocks) == 1 and [c.tag for c in blocks[0]]
            == ["outcomes"] + ["respcondition"] * len(items), error)
    outcomes = blocks[0].find("outcomes")
    require([c.tag for c in outcomes] == ["decvar"] and not outcomes[0].attrib, error)
    total = Decimal(0)
    for index, rule in enumerate(blocks[0].findall("respcondition")):
        require(rule.get("continue", "Yes") == "Yes"
                and [c.tag for c in rule] == ["conditionvar", "setvar", "displayfeedback"]
                and len(rule[0]) == 1, error)
        term, scoring = rule[0][0], rule[1]
        require(term.tag == "varequal"
                and term.attrib == {"respident": "OQT", "index": str(index)}
                and (term.text or "").strip() == str(index),
                f"{title}: Nur die Reihenfolge der Elemente als Loesung wird unterstuetzt.")
        value = (scoring.text or "").strip()
        require(scoring.get("action") == "Add"
                and scoring.get("varname", "SCORE") == "SCORE"
                and set(scoring.attrib) <= {"action", "varname"}
                and re.fullmatch(number, value), error)
        total += Decimal(value)
    require(total == points,
            f"{title}: Positionspunkte passen nicht zur Gesamtpunktzahl.")
    for entry in item.findall("itemfeedback"):
        require(not any((t.text or "").strip() for t in entry.iter("mattext")),
                f"{title}: Feedback bei Anordnung wird noch nicht unterstuetzt.")
    return OrderingQuestion(title, prompt, items, points)


def ordering_html(text):
    return "<p>" + html.escape(text, quote=False).replace("\n", "<br>") + "</p>"


"""

READ_DISPATCH = """        if questiontype == "assOrderingQuestion":
            questions.append(read_ordering_question(item, title, meta))
            continue
"""

WRITE_BLOCK = """        if isinstance(src, OrderingQuestion):
            q = ET.SubElement(quiz, "question", type="ordering")
            ET.SubElement(ET.SubElement(q, "name"), "text").text = src.title
            body = ET.SubElement(q, "questiontext", format="html")
            ET.SubElement(body, "text").text = ordering_html(src.text)
            general = ET.SubElement(q, "generalfeedback", format="html")
            ET.SubElement(general, "text").text = ""
            ET.SubElement(q, "defaultgrade").text = format(src.points, "f")
            ET.SubElement(q, "penalty").text = "0"
            ET.SubElement(q, "hidden").text = "0"
            ET.SubElement(q, "layouttype").text = "VERTICAL"
            ET.SubElement(q, "selecttype").text = "ALL"
            ET.SubElement(q, "selectcount").text = "2"
            ET.SubElement(q, "gradingtype").text = "ALL_OR_NOTHING"
            ET.SubElement(q, "showgrading").text = "SHOW"
            ET.SubElement(q, "numberingstyle").text = "none"
            for tag in ("correctfeedback", "partiallycorrectfeedback", "incorrectfeedback"):
                field = ET.SubElement(q, tag, format="html")
                ET.SubElement(field, "text").text = ""
            ET.SubElement(q, "shownumcorrect").text = "1"
            for number, text in enumerate(src.items, 1):
                answer = ET.SubElement(q, "answer", fraction=str(number), format="moodle_auto_format")
                ET.SubElement(answer, "text").text = text
            continue
"""

MAIN_BLOCK = """            if isinstance(q, OrderingQuestion):
                print(f"OK: {q.title}: ORDERING, {len(q.items)} Elemente, "
                      f"{q.points} Punkt(e), alles-oder-nichts")
                continue
"""

TESTS = r"""

class TestOrderingV017(qb_unittest.TestCase):
    SOURCE = "1795710783__0__qti_339.xml"

    def project(self):
        return QBPath(__file__).resolve().parent

    def reference(self):
        for pattern in ("moodle-ordering-reference.xml", "questions-KFS-Ordne*1644.xml"):
            found = sorted(self.project().glob(pattern))
            if found:
                return qb_et.parse(found[0]).getroot().findall("question")[0]
        raise AssertionError("Moodle-Ordering-Referenz nicht gefunden.")

    def convert(self, source, error=None):
        with qb_tempfile.TemporaryDirectory() as directory:
            output = QBPath(directory) / "moodle.xml"
            result = qb_subprocess.run(
                [qb_sys.executable, "-B", str(self.project() / "questionbridge_v017.py"),
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
    def answers(question):
        return [(a.get("fraction"), a.findtext("text")) for a in question.findall("answer")]

    @staticmethod
    def meta(tree, label, value):
        for f in tree.iter("qtimetadatafield"):
            if f.findtext("fieldlabel") == label:
                f.find("fieldentry").text = value
                return
        raise AssertionError(label)

    def test_ordering_matches_moodle_reference(self):
        q, = self.convert(self.project() / self.SOURCE)
        ref = self.reference()
        self.assertEqual(q.get("type"), "ordering")
        self.assertEqual(q.findtext("name/text"), "QB-ORDER-V017-REFEREN")
        self.assertEqual(q.findtext("questiontext/text"),
                         "<p>Ordne die Planeten nach ihrem Abstand zur Sonne.</p>")
        for tag in ("defaultgrade", "layouttype", "selecttype", "selectcount",
                    "gradingtype", "showgrading", "numberingstyle"):
            self.assertEqual(q.findtext(tag), ref.findtext(tag), tag)
        self.assertEqual(self.answers(q), self.answers(ref))
        self.assertEqual(self.answers(q), [("1", "Merkur"), ("2", "Venus"),
                                           ("3", "Erde"), ("4", "Mars")])

    def test_ordering_points_come_from_points_field(self):
        def edit(tree):
            self.meta(tree, "points", "8")
            for node in tree.iter("setvar"):
                node.text = "2"
        q, = self.variant(edit)
        self.assertEqual(QBDecimal(q.findtext("defaultgrade")), 8)

    def test_ordering_items_are_read_from_file(self):
        def edit(tree):
            texts = [n for n in tree.iter("mattext") if n.get("texttype") == "text/plain"]
            texts[-1].text = "Jupiter"
        q, = self.variant(edit)
        self.assertEqual([t for _, t in self.answers(q)],
                         ["Merkur", "Venus", "Erde", "Jupiter"])

    def test_ordering_position_points_must_add_up(self):
        def edit(tree):
            tree.findall(".//setvar")[0].text = "2"
        self.variant(edit, "Positionspunkte")

    def test_ordering_nested_answers_rejected(self):
        def edit(tree):
            for node in tree.iter("mattext"):
                if node.get("label") == "answerdepth":
                    node.text = "1"
                    return
        self.variant(edit, "Verschachtelte Anordnung")

    def test_ordering_other_solution_rejected(self):
        def edit(tree):
            node = tree.findall(".//varequal")[0]
            node.text = "1"
        self.variant(edit, "Reihenfolge der Elemente")

    def test_ordering_feedback_rejected(self):
        def edit(tree):
            tree.find(".//itemfeedback//mattext").text = "Hallo"
        self.variant(edit, "Feedback bei Anordnung")

    def test_ordering_without_shuffle_rejected(self):
        def edit(tree):
            tree.find(".//render_choice").set("shuffle", "No")
        self.variant(edit, "Mischen der Elemente")

    def test_ordering_zero_points_rejected(self):
        self.variant(lambda t: self.meta(t, "points", "0"), "Punktzahl")

    def test_ordering_duplicate_items_rejected(self):
        def edit(tree):
            texts = [n for n in tree.iter("mattext") if n.get("texttype") == "text/plain"]
            texts[-1].text = "Merkur"
        self.variant(edit, "Doppelte Elemente")
"""


def main():
    src = (ROOT / "questionbridge_v016.py").read_text(encoding="utf-8")
    src = replace_once(src, "QuestionBridge 0.16: ILIAS QTI choice, Kprim, Long Menu,",
                       "QuestionBridge 0.17: ILIAS QTI choice, Kprim, Long Menu, ordering,", "docstring")
    src = replace_once(src, "def read_questions(path):\n", CONVERTER_BLOCK + "def read_questions(path):\n", "read_questions")
    src = replace_once(src, '        if questiontype == "assLongMenu":\n',
                       READ_DISPATCH + '        if questiontype == "assLongMenu":\n', "dispatch")
    src = replace_once(src, '        q = ET.SubElement(quiz, "question", type="multichoice")\n',
                       WRITE_BLOCK + '        q = ET.SubElement(quiz, "question", type="multichoice")\n', "writer")
    src = replace_once(src, '            kind = "SC" if q.single else "MC"\n',
                       MAIN_BLOCK + '            kind = "SC" if q.single else "MC"\n', "main")
    (ROOT / "questionbridge_v017.py").write_text(src, encoding="utf-8")

    test = (ROOT / "test_questionbridge_v016.py").read_text(encoding="utf-8")
    test = test.replace("questionbridge_v016", "questionbridge_v017")
    test = replace_once(test, '        "1795707402__0__qti_339.xml",\n    ]\n',
                        '        "1795707402__0__qti_339.xml",\n        "1795710783__0__qti_339.xml",\n    ]\n', "sources")
    test = replace_once(test, '"kprime", "cloze"]', '"kprime", "cloze", "ordering"]', "types")
    test = replace_once(test, '\n\nif __name__ == "__main__":\n    qb_unittest.main(verbosity=2)',
                        TESTS + '\n\nif __name__ == "__main__":\n    qb_unittest.main(verbosity=2)', "tests")
    (ROOT / "test_questionbridge_v017.py").write_text(test, encoding="utf-8")
    print("Erzeugt: questionbridge_v017.py, test_questionbridge_v017.py")


main()
