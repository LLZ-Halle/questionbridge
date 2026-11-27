import contextlib, io, sys, tempfile, unittest
from decimal import Decimal
from pathlib import Path
import questionbridge_v020 as qb

BASE = Path(__file__).parent
HEAD = '<?xml version="1.0" encoding="utf-8"?><questestinterop><item ident="x" title="T"><itemmetadata><qtimetadata>'
TAIL = "</qtimetadata></itemmetadata>%s</item></questestinterop>"


def field(k, v):
    return f"<qtimetadatafield><fieldlabel>{k}</fieldlabel><fieldentry>{v}</fieldentry></qtimetadatafield>"


def horizontal(text="Der Hund bellt laut", points="4", separator="::", size="100", extra=""):
    meta = (field("QUESTIONTYPE", "assOrderingHorizontal") + field("points", points)
            + field("ordertext", text) + field("textsize", size) + field("separator", separator))
    pres = ('<presentation label="T"><flow><material><mattext texttype="text/plain">Frage'
            "</mattext></material></flow></presentation>")
    return HEAD + meta + TAIL % (pres + extra)


class HorizontalOrderingTests(unittest.TestCase):
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

    def test_whitespace_split(self):
        q, = self.read(horizontal("Der Hund  bellt\nlaut"))
        self.assertIsInstance(q, qb.HorizontalOrderingQuestion)
        self.assertEqual(q.items, ["Der", "Hund", "bellt", "laut"])
        self.assertEqual(q.points, Decimal(4))

    def test_separator_split_keeps_spaces(self):
        q, = self.read(horizontal("Der Hund :: bellt::laut"))
        self.assertEqual(q.items, ["Der Hund", "bellt", "laut"])

    def test_output(self):
        code, xml, out = self.convert(horizontal())
        self.assertEqual(code, 0)
        for part in ("<layouttype>HORIZONTAL</layouttype>", "<gradingtype>ALL_OR_NOTHING</gradingtype>",
                     "<defaultgrade>4</defaultgrade>", '<answer fraction="4" format="moodle_auto_format">'):
            self.assertIn(part, xml)
        self.assertIn("ORDERING (horizontal), 4 Elemente, 4 Punkt(e), alles-oder-nichts", out)

    def test_rejections(self):
        fb = '<itemfeedback ident="f"><flow_mat><material><mattext>Gut</mattext></material></flow_mat></itemfeedback>'
        cases = {
            "one item": horizontal("Hund"),
            "empty item": horizontal("Der::::Hund"),
            "empty text": horizontal(""),
            "duplicates": horizontal("Hund Hund bellt"),
            "textsize": horizontal(size="120"),
            "separator": horizontal(separator=";;"),
            "zero points": horizontal(points="0"),
            "bad points": horizontal(points="abc"),
            "feedback": horizontal(extra=fb),
            "scoring": horizontal(extra="<resprocessing/>"),
        }
        for name, xml in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                self.read(xml)

    def test_vertical_unchanged(self):
        ref = BASE / "1795710783__0__qti_339.xml"
        if not ref.exists():
            self.skipTest("Referenz fehlt")
        q, = qb.read_questions(ref)
        self.assertNotIsInstance(q, qb.HorizontalOrderingQuestion)

    def test_real_reference(self):
        ref = BASE / "1795789135__0__qti_339.xml"
        if not ref.exists():
            self.skipTest("Referenz fehlt")
        q, = qb.read_questions(ref)
        self.assertEqual((q.title, q.items, q.points),
                         ("QB-ORDH-V020-REFERENZ", ["Der", "Hund", "bellt", "laut"], Decimal(4)))


if __name__ == "__main__":
    unittest.main()
