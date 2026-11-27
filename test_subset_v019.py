import contextlib, io, sys, tempfile, unittest
from decimal import Decimal
from pathlib import Path
import questionbridge_v019 as qb

BASE = Path(__file__).parent
HEAD = '<?xml version="1.0" encoding="utf-8"?><questestinterop><item ident="x" title="T"><itemmetadata><qtimetadata>'
TAIL = "</qtimetadata></itemmetadata>%s</item></questestinterop>"


def field(k, v):
    return f"<qtimetadatafield><fieldlabel>{k}</fieldlabel><fieldentry>{v}</fieldentry></qtimetadatafield>"


def subset(terms=("Berlin", "Paris", "Rom"), count=2, points="2", total=None, rating="ci",
           grouped=True, feedback="", extra_rule=""):
    total = str(count * int(points)) if total is None else total
    meta = (field("QUESTIONTYPE", "assTextSubset") + field("textrating", rating)
            + field("correctanswers", count) + field("points", total))
    fields = "".join(f'<response_str ident="TEXTSUBSET_{n}" rcardinality="Single">'
                     '<render_fib fibtype="String" columns="9"></render_fib></response_str>'
                     for n in range(1, count + 1))
    pres = ('<presentation label="T"><flow><material><mattext texttype="text/plain">Frage</mattext>'
            f"</material>{fields}</flow></presentation>")
    rules = ""
    for n in range(1, count + 1):
        groups = [",".join(terms)] if grouped else list(terms)
        for g in groups:
            rules += ('<respcondition continue="Yes"><conditionvar>'
                      f'<varsubset respident="TEXTSUBSET_{n}">{g}</varsubset></conditionvar>'
                      f'<setvar varname="matches" action="Add">{points}</setvar>'
                      f'<displayfeedback feedbacktype="Response" linkrefid="Matches_{n}"/></respcondition>')
    proc = ('<resprocessing><outcomes><decvar></decvar><decvar varname="matches" defaultval="0"/>'
            f"</outcomes>{rules}{extra_rule}</resprocessing>")
    fb = "".join(f'<itemfeedback ident="Matches_{n}" view="All"><flow_mat><material>'
                 f"<mattext>{feedback}</mattext></material></flow_mat></itemfeedback>"
                 for n in range(1, count + 1))
    return HEAD + meta + TAIL % (pres + proc + fb)


class Base(unittest.TestCase):
    def read(self, xml):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "q.xml"); p.write_text(xml, encoding="utf-8")
            return qb.read_questions(p)

    def convert(self, xml):
        with tempfile.TemporaryDirectory() as d:
            p, out = Path(d, "q.xml"), Path(d, "o.xml")
            p.write_text(xml, encoding="utf-8")
            old, buf = sys.argv, io.StringIO()
            sys.argv = ["qb", str(p), str(out)]
            try:
                with contextlib.redirect_stdout(buf):
                    code = qb.main()
            finally:
                sys.argv = old
            return code, (out.read_text(encoding="utf-8") if out.exists() else ""), buf.getvalue()


class SubsetTests(Base):
    def test_grouped(self):
        q, = self.read(subset())
        self.assertIsInstance(q, qb.SubsetQuestion)
        self.assertEqual(qb.cloze_points(q), 4)
        self.assertEqual(qb.cloze_markup(q).count("{2:SHORTANSWER:=Berlin~=Paris~=Rom}"), 2)

    def test_single_terms_per_rule(self):
        q, = self.read(subset(grouped=False))
        self.assertEqual(qb.cloze_points(q), 4)

    def test_case_sensitive(self):
        q, = self.read(subset(rating="cs"))
        self.assertIn("SHORTANSWER_C", qb.cloze_markup(q))

    def test_output_and_hint(self):
        code, xml, out = self.convert(subset())
        self.assertEqual(code, 0)
        self.assertIn("<defaultgrade>4</defaultgrade>", xml)
        self.assertIn("SUBSET, 2 Felder, 4 Punkt(e)", out)
        self.assertIn("HINWEIS", out)

    def test_unequal_points_rejected(self):
        xml = subset(terms=("Berlin",), grouped=False, count=1, points="2", total="3",
                     extra_rule='<respcondition continue="Yes"><conditionvar><varsubset respident="TEXTSUBSET_1">Paris</varsubset></conditionvar><setvar varname="matches" action="Add">3</setvar><displayfeedback feedbacktype="Response" linkrefid="Matches_1"/></respcondition>')
        with self.assertRaisesRegex(ValueError, "Ungleiche Punkte"):
            self.read(xml)

    def test_rejections(self):
        cases = {
            "rating": subset(rating="lcs"),
            "fewer terms": subset(terms=("Berlin",)),
            "dup terms": subset(terms=("Berlin", "berlin", "Rom")),
            "special": subset(terms=("Ber{lin", "Paris", "Rom")),
            "total": subset(total="5"),
            "feedback": subset(feedback="Gut"),
            "float points": subset(points="2.5", total="5"),
            "zero points": subset(points="0", total="0"),
        }
        for name, xml in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                self.read(xml)

    def test_real_references(self):
        gleich, ref = BASE / "1795785886__0__qti_339.xml", BASE / "1795785227__0__qti_339.xml"
        if not gleich.exists() or not ref.exists():
            self.skipTest("Referenzdateien fehlen")
        q, = qb.read_questions(gleich)
        self.assertEqual(qb.cloze_points(q), 4)
        with self.assertRaisesRegex(ValueError, "Ungleiche Punkte"):
            qb.read_questions(ref)


def upload(maxsize="", ext="", points="10", extra=""):
    meta = (field("QUESTIONTYPE", "assFileUpload") + field("points", points)
            + field("maxsize", maxsize) + field("allowedextensions", ext))
    pres = ('<presentation label="T"><flow><material><mattext texttype="text/plain">Frage'
            "</mattext></material></flow></presentation>")
    return HEAD + meta + TAIL % (pres + extra)


class UploadTests(Base):
    def test_settings_and_hint(self):
        code, xml, out = self.convert(upload("1048576", "pdf, DOCX"))
        self.assertEqual(code, 0)
        for part in ("<maxbytes>1048576</maxbytes>", "<filetypeslist>.pdf,.docx</filetypeslist>",
                     "<attachments>2</attachments>", "<defaultgrade>10</defaultgrade>"):
            self.assertIn(part, xml)
        self.assertIn("HINWEIS", out)

    def test_empty_settings(self):
        q, = self.read(upload())
        self.assertEqual((q.max_bytes, q.extensions), (0, ()))

    def test_rejections(self):
        for kwargs in ({"maxsize": "1500000"}, {"ext": "*.pdf"}, {"ext": "pdf,pdf"}, {"points": "0"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.read(upload(**kwargs))


if __name__ == "__main__":
    unittest.main()
