#!/usr/bin/env python3
# Erzeugt questionbridge_v015.py und test_questionbridge_v015.py aus den v014-Dateien.
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent


def replace_once(text, old, new, label):
    if text.count(old) != 1:
        sys.exit(f"Anker nicht eindeutig gefunden ({text.count(old)}x): {label}")
    return text.replace(old, new)


CONVERTER_BLOCK = r"""@dataclass
class KprimQuestion:
    title: str
    text: str
    statements: list
    points: Decimal
    shuffle: bool


def kprim_value(node, title):
    value = (node.text or "").strip()
    require(len(node) == 0 and value in {"0", "1"},
            f"{title}: Kprim-Bewertung wird nur als alles-oder-nichts unterstuetzt.")
    return value == "1"


def read_kprim_question(item, title, meta):
    error = f"{title}: Nicht unterstuetzte Kprim-Struktur."
    scoring_error = f"{title}: Kprim-Bewertung wird nur als alles-oder-nichts unterstuetzt."
    answer_type = meta.get("answer_type")
    require(answer_type == "singleLine",
            f"{title}: Kprim-Antworttyp {answer_type!r} wird nicht unterstuetzt.")
    labels_setting = meta.get("option_label_setting")
    require(labels_setting == "right_wrong",
            f"{title}: Kprim-Beschriftung {labels_setting!r} wird nicht unterstuetzt "
            "(nur right_wrong).")

    presentation = item.find("presentation")
    require(presentation is not None, error)
    prompts = presentation.findall("./flow/material/mattext")
    groups = presentation.findall("./flow/response_lid")
    require(len(prompts) == 1 and len(groups) == 1, error)
    prompt = plain(prompts[0])
    group = groups[0]
    require(group.get("ident") and group.get("rcardinality") == "Multiple", error)
    render = group.find("render_choice")
    require(render is not None and len(group) == 1
            and len(render.findall("response_label")) == len(render), error)
    shuffle = render.get("shuffle", "No")
    require(shuffle in {"Yes", "No"}, "Unbekannte Mischoption.")
    labels = render.findall("response_label")
    require(len(labels) >= 2, f"{title}: Mindestens zwei Aussagen erforderlich.")
    texts = {}
    for label in labels:
        key = label.get("ident")
        nodes = label.findall("./material/mattext")
        require(key and key not in texts and len(nodes) == 1 and len(label) == 1
                and set(label.attrib) == {"ident"}, error)
        text = plain(nodes[0])
        require(text.strip(), f"{title}: Leere Kprim-Aussage.")
        texts[key] = text

    blocks = item.findall("resprocessing")
    require(len(blocks) == 1 and blocks[0].get("scoremodel") is None
            and all(c.tag in {"outcomes", "respcondition"} for c in blocks[0]), error)
    outcomes = blocks[0].findall("outcomes")
    require(len(outcomes) == 1 and [c.tag for c in outcomes[0]] == ["decvar"]
            and outcomes[0][0].get("varname", "SCORE") == "SCORE", error)

    each, all_rules, none_rules = {}, [], []
    for rule in blocks[0].findall("respcondition"):
        require(rule.get("continue", "Yes") == "Yes"
                and rule.find("conditionvar") is not None
                and [c.tag for c in rule][0] == "conditionvar"
                and len(rule[0]) == 1, error)
        term = rule[0][0]
        if term.tag == "varequal":
            require([c.tag for c in rule] == ["conditionvar", "displayfeedback"]
                    and set(term.attrib) == {"respident"}
                    and term.get("respident") in texts
                    and term.get("respident") not in each, error)
            each[term.get("respident")] = kprim_value(term, title)
        elif term.tag == "and":
            all_rules.append(rule)
        elif term.tag == "or":
            none_rules.append(rule)
        else:
            require(False, scoring_error)
    require(len(all_rules) == 1 and len(none_rules) == 1, scoring_error)
    all_rule, none_rule = all_rules[0], none_rules[0]
    require([c.tag for c in all_rule] == ["conditionvar", "setvar"]
            and [c.tag for c in none_rule] == ["conditionvar", "setvar"], scoring_error)

    all_term, none_term = all_rule[0][0], none_rule[0][0]
    require(len(all_term) == len(texts) and len(none_term) == len(texts)
            and all(t.tag == "varequal" and set(t.attrib) == {"respident"}
                    for t in all_term)
            and all(t.tag == "not" and not t.attrib and len(t) == 1
                    and t[0].tag == "varequal" and set(t[0].attrib) == {"respident"}
                    for t in none_term), scoring_error)
    all_values = {t.get("respident"): kprim_value(t, title) for t in all_term}
    none_values = {t[0].get("respident"): kprim_value(t[0], title) for t in none_term}
    require(set(all_values) == set(texts) and len(all_values) == len(texts)
            and none_values == all_values, scoring_error)
    require(each == all_values, f"{title}: Kprim-Loesung ist widerspruechlich.")

    def points(rule):
        scoring = rule.find("setvar")
        value = (scoring.text or "").strip()
        require(scoring.get("action") == "Add"
                and scoring.get("varname", "SCORE") == "SCORE"
                and set(scoring.attrib) <= {"action", "varname"}
                and re.fullmatch(r"[0-9]{1,6}(?:[.][0-9]{1,3})?", value), scoring_error)
        return Decimal(value)

    full = points(all_rule)
    require(full > 0 and points(none_rule) == 0, scoring_error)
    maximum = outcomes[0][0].get("maxvalue")
    if maximum is not None:
        require(re.fullmatch(r"[0-9]{1,6}(?:[.][0-9]{1,3})?", maximum.strip())
                and Decimal(maximum.strip()) == full,
                f"{title}: Kprim-Maximalpunktzahl passt nicht zur Bewertung.")

    for entry in item.findall("itemfeedback"):
        require(not any((t.text or "").strip() for t in entry.iter("mattext")),
                f"{title}: Feedback bei Kprim wird noch nicht unterstuetzt.")
    return KprimQuestion(title, prompt, [(texts[k], each[k]) for k in texts],
                         full, shuffle == "Yes")


def kprim_html(text):
    return "<p>" + html.escape(text, quote=False).replace("\n", "<br>") + "</p>"


"""

READ_DISPATCH = """        if questiontype == "assKprimChoice":
            questions.append(read_kprim_question(item, title, meta))
            continue
"""

WRITE_BLOCK = """        if isinstance(src, KprimQuestion):
            q = ET.SubElement(quiz, "question", type="kprime")
            ET.SubElement(ET.SubElement(q, "name"), "text").text = src.title
            body = ET.SubElement(q, "questiontext", format="html")
            ET.SubElement(body, "text").text = kprim_html(src.text)
            general = ET.SubElement(q, "generalfeedback", format="html")
            ET.SubElement(general, "text").text = ""
            ET.SubElement(q, "defaultgrade").text = format(src.points, "f")
            ET.SubElement(q, "penalty").text = "0"
            ET.SubElement(q, "hidden").text = "0"
            ET.SubElement(ET.SubElement(q, "scoringmethod"), "text").text = "kprimeonezero"
            ET.SubElement(q, "shuffleanswers").text = "true" if src.shuffle else "false"
            ET.SubElement(q, "numberofrows").text = str(len(src.statements))
            ET.SubElement(q, "numberofcolumns").text = "2"
            for number, (text, _) in enumerate(src.statements, 1):
                row = ET.SubElement(q, "row", number=str(number))
                option = ET.SubElement(row, "optiontext", format="html")
                ET.SubElement(option, "text").text = kprim_html(text)
                feedback = ET.SubElement(row, "feedbacktext", format="html")
                ET.SubElement(feedback, "text").text = ""
            for number, label in enumerate(("Richtig", "Falsch"), 1):
                column = ET.SubElement(q, "column", number=str(number))
                response = ET.SubElement(column, "responsetext", format="moodle_auto_format")
                ET.SubElement(response, "text").text = label
            for number, (_, right) in enumerate(src.statements, 1):
                for column, value in ((1, right), (2, not right)):
                    weight = ET.SubElement(q, "weight", rownumber=str(number),
                                           columnnumber=str(column))
                    ET.SubElement(weight, "value").text = "1.000" if value else "0.000"
            continue
"""

MAIN_BLOCK = """            if isinstance(q, KprimQuestion):
                print(f"OK: {q.title}: KPRIM, {len(q.statements)} Aussagen, "
                      f"{q.points} Punkt(e), alles-oder-nichts")
                continue
"""

TESTS = r"""

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
                [qb_sys.executable, "-B", str(self.project() / "questionbridge_v015.py"),
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
"""


def main():
    src = (ROOT / "questionbridge_v014.py").read_text(encoding="utf-8")
    src = replace_once(src, "QuestionBridge 0.14: ILIAS QTI choice, numerical, matching, cloze, essay and keyword text questions",
                       "QuestionBridge 0.15: ILIAS QTI choice, Kprim, numerical, matching, cloze, essay and keyword text questions", "docstring")
    src = replace_once(src, "def read_questions(path):\n", CONVERTER_BLOCK + "def read_questions(path):\n", "read_questions")
    src = replace_once(src, '        require(questiontype in {"assSingleChoice", "assMultipleChoice"},',
                       READ_DISPATCH + '        require(questiontype in {"assSingleChoice", "assMultipleChoice"},', "dispatch")
    src = replace_once(src, '        q = ET.SubElement(quiz, "question", type="multichoice")\n',
                       WRITE_BLOCK + '        q = ET.SubElement(quiz, "question", type="multichoice")\n', "writer")
    src = replace_once(src, '            kind = "SC" if q.single else "MC"\n',
                       MAIN_BLOCK + '            kind = "SC" if q.single else "MC"\n', "main")
    (ROOT / "questionbridge_v015.py").write_text(src, encoding="utf-8")

    test = (ROOT / "test_questionbridge_v014.py").read_text(encoding="utf-8")
    test = test.replace("questionbridge_v014", "questionbridge_v015")
    test = replace_once(test, '        "1795700896__0__qti_341.xml",\n    ]\n',
                        '        "1795700896__0__qti_341.xml",\n        "1795702712__0__qti_339.xml",\n    ]\n', "sources")
    test = replace_once(test, '"essay", "shortanswer", "shortanswer", "shortanswer"]',
                        '"essay", "shortanswer", "shortanswer", "shortanswer", "kprime"]', "types")
    test = replace_once(test, '\n\nif __name__ == "__main__":\n    qb_unittest.main(verbosity=2)',
                        TESTS + '\n\nif __name__ == "__main__":\n    qb_unittest.main(verbosity=2)', "tests")
    (ROOT / "test_questionbridge_v015.py").write_text(test, encoding="utf-8")
    print("Erzeugt: questionbridge_v015.py, test_questionbridge_v015.py")


main()
