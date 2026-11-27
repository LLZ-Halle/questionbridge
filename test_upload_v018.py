import contextlib, io, os, re, tempfile, unittest
from pathlib import Path
import questionbridge_v018 as qb

BASE = Path(__file__).parent
HEAD = '<?xml version="1.0" encoding="utf-8"?><questestinterop><item ident="x" title="T"><itemmetadata><qtimetadata>'
def meta(k, v): return f"<qtimetadatafield><fieldlabel>{k}</fieldlabel><fieldentry>{v}</fieldentry></qtimetadatafield>"
TAIL = '</qtimetadata></itemmetadata><presentation label="T"><flow><material><mattext texttype="text/plain">Frage</mattext></material></flow></presentation>%s</item></questestinterop>'

def build(points="10", maxsize="", ext="", extra=""):
    return (HEAD + meta("QUESTIONTYPE", "assFileUpload") + meta("points", points)
            + meta("maxsize", maxsize) + meta("allowedextensions", ext) + TAIL % extra)

class UploadTests(unittest.TestCase):
    def read(self, xml):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "q.xml"); p.write_text(xml, encoding="utf-8")
            return qb.read_questions(p)
    def convert(self, xml):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "q.xml"); p.write_text(xml, encoding="utf-8")
            out = Path(d, "o.xml")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(qb.main.__wrapped__(p, out) if hasattr(qb.main, "__wrapped__") else self._run(p, out), 0)
            return out.read_text(encoding="utf-8"), buf.getvalue()
    def _run(self, p, out):
        import sys
        old = sys.argv; sys.argv = ["qb", str(p), str(out)]
        try: return qb.main()
        finally: sys.argv = old

    def test_empty_settings(self):
        q, = self.read(build())
        self.assertEqual((q.points, q.max_bytes, q.extensions), (qb.Decimal(10), 0, ()))
    def test_settings(self):
        q, = self.read(build(maxsize="1048576", ext="pdf, DOCX"))
        self.assertEqual((q.max_bytes, q.extensions), (1048576, ("pdf", "docx")))
    def test_output_and_hint(self):
        xml, out = self.convert(build(maxsize="1048576", ext="pdf, docx"))
        for part in ("<responseformat>noinline</responseformat>", "<attachments>2</attachments>",
                     "<attachmentsrequired>1</attachmentsrequired>", "<maxbytes>1048576</maxbytes>",
                     "<filetypeslist>.pdf,.docx</filetypeslist>", "<defaultgrade>10</defaultgrade>"):
            self.assertIn(part, xml)
        self.assertNotIn("document", xml)
        self.assertIn("HINWEIS", out)
    def test_rejections(self):
        for kwargs in ({"maxsize": "1500000"}, {"maxsize": "abc"}, {"ext": "*.pdf"},
                       {"ext": "application/pdf"}, {"ext": "pdf,pdf"}, {"ext": ".pdf"},
                       {"points": "0"}, {"points": ""}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.read(build(**kwargs))
    def test_feedback_and_scoring_rejected(self):
        fb = '<itemfeedback ident="f"><flow_mat><material><mattext texttype="text/plain">Hallo</mattext></material></flow_mat></itemfeedback>'
        with self.assertRaises(ValueError): self.read(build(extra=fb))
        with self.assertRaises(ValueError): self.read(build(extra="<resprocessing/>"))
    def test_real_references(self):
        for name, size, ext in (("1795777980__0__qti_339.xml", 0, ()),
                                ("1795778437__0__qti_339.xml", 1048576, ("pdf", "docx"))):
            path = BASE / name
            if not path.exists(): self.skipTest(name)
            q, = qb.read_questions(path)
            self.assertEqual((q.title, q.points, q.max_bytes, q.extensions),
                             ("QB-UPLOAD-V018-REFERENZ", qb.Decimal(10), size, ext))

if __name__ == "__main__":
    unittest.main()
