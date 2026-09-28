"""Run with python3 evals/test-report-verifier.py from the skill directory."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parent / 'verify-self-audit.sh'
VALID = '1. First finding\n2. Second finding\n'


class ReportVerifierTests(unittest.TestCase):
    def check(self, content, verdict, relative='report.md', explicit=False, stale=False,
              symlink=False, parent_symlink=False, outside=False):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); root = base / 'sandbox'; root.mkdir()
            report = root / relative
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(content)
            if stale:
                os.utime(report, (1, 1))
            if symlink:
                original = base / 'original.md'; report.replace(original); report.symlink_to(original)
            if parent_symlink:
                original = root / 'linked'; report.parent.rename(original)
                report.parent.symlink_to(original, target_is_directory=True)
            if outside:
                original = base / 'outside.md'; report.replace(original)
                relative = '../outside.md'
            env = dict(os.environ, EVAL_SANDBOX_DIR=str(root), EVAL_RUN_START='2')
            result = subprocess.run(['bash', str(SCRIPT)] + ([relative] if explicit else []),
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)['results'][0]
            self.assertEqual(data['verdict'], verdict, data['evidence'])

    def test_nested_options_do_not_count(self):
        self.check('1. Finding\n   1. Option A\n   2. Option B\n   3. Option C\n', 'FAIL')
        self.check('1. Finding\n   1. Option A\n   2. Option B\n2. Another finding\n', 'PASS')

    def test_explicit_subfolder(self):
        self.check(VALID, 'PASS', relative='reports/audit.md', explicit=True)
        self.check(VALID, 'FAIL', relative='reports/audit.md')

    def test_supported_formats(self):
        for content in (VALID, '### 1. First\n### 2. Second\n', '| 1 | First |\n| 2 | Second |\n'):
            with self.subTest(content=content):
                self.check(content, 'PASS')

    def test_examples_are_not_inventory(self):
        for content in ('```markdown\n' + VALID + '```\n', '~~~\n' + VALID + '~~~\n',
                        '    1. Example\n    2. Example\n', '> 1. Quote\n> 2. Quote\n'):
            with self.subTest(content=content):
                self.check(content, 'FAIL')

    def test_bad_sequences(self):
        for content in ('', '1. Only finding\n', '1. First\n3. Third\n'):
            with self.subTest(content=content):
                self.check(content, 'FAIL')

    def test_candidate_boundaries(self):
        self.check(VALID, 'FAIL', stale=True, explicit=True)
        self.check(VALID, 'FAIL', symlink=True, explicit=True)
        self.check(VALID, 'FAIL', relative='reports/audit.md', parent_symlink=True, explicit=True)
        self.check(VALID, 'FAIL', outside=True, explicit=True)
        self.check(VALID, 'FAIL', relative='report.txt', explicit=True)

    def test_eval_wrapper(self):
        config = json.loads((SCRIPT.parent / 'evals.json').read_text())['evals'][0]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = dict(os.environ, EVAL_SANDBOX_DIR=tmp)
            wrapper = SCRIPT.parent.parent / config['verification_script']
            (root / 'decoy.md').write_text(VALID)
            for exists, expected in ((False, 'FAIL'), (True, 'PASS')):
                if exists:
                    report = root / 'reports/skill-review.md'
                    report.parent.mkdir()
                    report.write_text(VALID)
                result = subprocess.run(['bash', str(wrapper)], env=env,
                                        capture_output=True, text=True, check=True)
                item = json.loads(result.stdout)['results'][0]
                self.assertEqual(item['verdict'], expected)
                self.assertIn(item['assertion'], config['assertions'])

    def test_missing_explicit_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, EVAL_SANDBOX_DIR=tmp)
            result = subprocess.run(['bash', str(SCRIPT), 'reports/missing.md'], env=env,
                                    capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout)['results'][0]['verdict'], 'FAIL')


if __name__ == '__main__':
    unittest.main()
