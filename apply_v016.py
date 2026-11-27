#!/usr/bin/env python3
# Erzeugt questionbridge_v016.py und test_questionbridge_v016.py aus den v015-Dateien.
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent


def replace_once(text, old, new, label):
    if text.count(old) != 1:
        sys.exit(f"Anker nicht eindeutig gefunden ({text.count(old)}x): {label}")
    return text.replace(old, new)


CONVERTER_BLOCK = r"""LONGMENU_PLACEHOLDER = re.compile(r"\[Longmenu ([0-9]+)\]")


def read_longmenu_question(item, title, meta):
    error = f"{title}: Nicht unterstuetzte Long-Menu-Struktur."
    try:
        types = json.loads(meta.get("gapTypes") or "")
    except ValueError:
        types = None
    require(isinstance(types, list) and types
            and all(type(t) is int and t in (0, 1) for t in types),
            f"{title}: Long-Menu-Lueckentyp wird nicht unterstuetzt.")
    require((meta.get("identical_scoring") or "").strip() in {"", "0"},
            f"{title}: Identische Bewertung wird bei Long Menu nicht unterstuetzt.")

    presentation = item.find("presentation")
    require(presentation is not None and len(presentation) == 1, error)
    flow = presentation.find("flow")
    require(flow is not None and len(flow) == 2 + len(types)
            and [c.tag for c in flow] == ["material", "material"] + ["response_str"] * len(types),
            error)
    parts_text = []
    for material in flow[:2]:
        nodes = material.findall("mattext")
        require(len(material) == 1 and len(nodes) == 1, error)
        text = plain(nodes[0])
        require("{" not in text and "}" not in text,
                f"{title}: Geschweifte Klammern im Text werden nicht unterstuetzt.")
        parts_text.append(text)
    prompt, gap_text = parts_text

    numbers = LONGMENU_PLACEHOLDER.findall(gap_text)
    require(numbers == [str(n) for n in range(1, len(types) + 1)],
            f"{title}: Platzhalter [Longmenu n] passen nicht zu den Luecken.")

    options = {}
    for number, response in enumerate(flow[2:], 1):
        ident = f"LongMenu_{number}"
        require(response.attrib == {"ident": ident, "rcardinality": "Single"}
                and len(response) >= 1
                and all(c.tag == "response_label" for c in response), error)
        values = []
        for label in response:
            nodes = label.findall("./material/fieldentry")
            require(len(nodes) == 1 and len(label) == 1 and len(label[0]) == 1
                    and set(label.attrib) == {"ident"}, error)
            value = nodes[0].text or ""
            require(value.strip(), f"{title}: Leere Antwortoption in Luecke {number}.")
            values.append(value)
        require(len(set(values)) == len(values),
                f"{title}: Doppelte Antwortoption in Luecke {number}.")
        options[ident] = values

    blocks = item.findall("resprocessing")
    require(len(blocks) == 1 and all(c.tag in {"outcomes", "respcondition"} for c in blocks[0]),
            error)
    outcomes = blocks[0].findall("outcomes")
    require(len(outcomes) == 1 and [c.tag for c in outcomes[0]] == ["decvar"], error)
    scores = {}
    for rule in blocks[0].findall("respcondition"):
        require(rule.get("continue", "Yes") == "Yes"
                and [c.tag for c in rule] == ["conditionvar", "setvar", "displayfeedback"]
                and len(rule[0]) == 1, error)
        term, scoring = rule[0][0], rule[1]
        require(term.tag == "varequal" and set(term.attrib) == {"respident"}
                and term.get("respident") in options, error)
        require(scoring.get("action") == "Add"
                and scoring.get("varname", "SCORE") == "SCORE"
                and set(scoring.attrib) <= {"action", "varname"}, error)
        score = Decimal((scoring.text or "").strip())
        require(score.is_finite() and score == score.to_integral_value()
                and 0 <= score <= 1000,
                f"{title}: Punkte pro Luecke muessen ganzzahlig sein.")
        key = (term.get("respident"), term.text or "")
        require(key[1] in options[key[0]] and key not in scores, error)
        scores[key] = int(score)
    require(len(scores) == sum(len(v) for v in options.values()),
            f"{title}: Antwortoption ohne Bewertungsregel.")
    for entry in item.findall("itemfeedback"):
        require(not any((t.text or "").strip() for t in entry.iter("mattext")),
                f"{title}: Feedback bei Long Menu wird noch nicht unterstuetzt.")

    gaps = []
    for number, kind in enumerate(types, 1):
        ident = f"LongMenu_{number}"
        positive = [(o, scores[(ident, o)]) for o in options[ident] if scores[(ident, o)] > 0]
        require(positive, f"{title}: Luecke {number} hat keine richtige Antwort.")
        require(len({s for _, s in positive}) == 1,
                f"{title}: Luecke {number}: ungleiche Punkte der richtigen Antworten "
                "werden nicht unterstuetzt.")
        weight = positive[0][1]
        if kind == 0:
            require(len(positive) == 1,
                    f"{title}: Auswahlluecke {number} braucht genau eine richtige Antwort.")
            all_options = tuple(cloze_value(o, title) for o in options[ident])
            gaps.append(ClozeGap("choice", weight=weight, answers=all_options,
                                 correct=positive[0][0], shuffle=False))
        else:
            gaps.append(ClozeGap("text", weight=weight, case_sensitive=True,
                                 answers=tuple(cloze_value(o, title) for o, _ in positive)))

    def clean(text):
        return html.escape(text, quote=False).replace("\n", "<br>")

    parts = [clean(prompt) + "<br>"]
    position = 0
    for match, gap in zip(LONGMENU_PLACEHOLDER.finditer(gap_text), gaps):
        parts.append(clean(gap_text[position:match.start()]))
        parts.append(gap)
        position = match.end()
    parts.append(clean(gap_text[position:]))
    return ClozeQuestion(title, parts)


"""

READ_DISPATCH = """        if questiontype == "assLongMenu":
            questions.append(read_longmenu_question(item, title, meta))
            continue
"""

TESTS = r"""

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
"""


def main():
    src = (ROOT / "questionbridge_v015.py").read_text(encoding="utf-8")
    src = replace_once(src, "QuestionBridge 0.15: ILIAS QTI choice, Kprim,",
                       "QuestionBridge 0.16: ILIAS QTI choice, Kprim, Long Menu,", "docstring")
    src = replace_once(src, "import html\nimport re\n", "import html\nimport json\nimport re\n", "import")
    src = replace_once(src, "def read_questions(path):\n", CONVERTER_BLOCK + "def read_questions(path):\n", "read_questions")
    src = replace_once(src, '        if questiontype == "assKprimChoice":\n',
                       READ_DISPATCH + '        if questiontype == "assKprimChoice":\n', "dispatch")
    (ROOT / "questionbridge_v016.py").write_text(src, encoding="utf-8")

    test = (ROOT / "test_questionbridge_v015.py").read_text(encoding="utf-8")
    test = test.replace("questionbridge_v015", "questionbridge_v016")
    test = replace_once(test, '        "1795702712__0__qti_339.xml",\n    ]\n',
                        '        "1795702712__0__qti_339.xml",\n        "1795707402__0__qti_339.xml",\n    ]\n', "sources")
    test = replace_once(test, '"shortanswer", "kprime"]', '"shortanswer", "kprime", "cloze"]', "types")
    test = replace_once(test, '\n\nif __name__ == "__main__":\n    qb_unittest.main(verbosity=2)',
                        TESTS + '\n\nif __name__ == "__main__":\n    qb_unittest.main(verbosity=2)', "tests")
    (ROOT / "test_questionbridge_v016.py").write_text(test, encoding="utf-8")
    print("Erzeugt: questionbridge_v016.py, test_questionbridge_v016.py")


main()
