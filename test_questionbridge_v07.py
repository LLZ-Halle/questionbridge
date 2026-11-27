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
        p = subprocess.run([sys.executable, str(ROOT / 'questionbridge_v07.py'),
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
