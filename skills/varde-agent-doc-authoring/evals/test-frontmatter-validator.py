# /// script
# requires-python = ">=3.9"
# dependencies = ["pyyaml>=6,<7"]
# ///
"""Run with uv run evals/test-frontmatter-validator.py from the skill directory."""
import runpy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

VALIDATOR = Path(__file__).resolve().parents[1] / 'scripts/validate-frontmatter.py'
validator = runpy.run_path(str(VALIDATOR))


class FrontmatterTests(unittest.TestCase):
    def validate(self, extra, valid=True):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / 'sample'
            skill.mkdir()
            (skill / 'SKILL.md').write_text(
                '---\nname: sample\ndescription: Example skill\n' + extra + '---\n# Sample\n'
            )
            result = subprocess.run(
                [sys.executable, str(VALIDATOR), '--json', str(skill)],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0 if valid else 1, result.stderr or result.stdout)
            data = json.loads(result.stdout)[0]
            self.assertEqual(data['ok'], valid)
            if not valid:
                self.assertTrue(data['errors'])
            return data

    def test_duplicate_keys(self):
        for extra in (
            'name: sample\n',
            'description: Different description\n',
            'metadata:\n  owner: one\n  owner: two\n',
            'defaults: &defaults\n  owner: one\n  owner: two\nmetadata:\n  <<: *defaults\n',
            'metadata:\n  <<: {owner: one}\n  <<: {owner: two}\n',
        ):
            with self.subTest(extra=extra):
                data = self.validate(extra, valid=False)
                self.assertIn('duplicate key', data['errors'][0])

    def test_unique_and_mixed_unknown_keys(self):
        self.validate('metadata:\n  owner: one\n')
        data = self.validate('1: foo\nextra: bar\n')
        self.assertEqual(len(data['warnings']), 2)

    def test_merge_overrides_and_aliases(self):
        for extra in (
            'metadata:\n  <<: {owner: inherited}\n  owner: explicit\n',
            'metadata:\n  <<: [{owner: first}, {owner: second}]\n',
            'defaults: &defaults\n  <<: {owner: inherited}\n  owner: explicit\nmetadata:\n  <<: *defaults\n',
            'defaults: &defaults\n  <<: {owner: inherited}\n  owner: explicit\nmetadata: *defaults\n',
        ):
            with self.subTest(extra=extra):
                self.validate(extra)
                self.assertEqual(yaml.load(extra, Loader=validator['UniqueKeyLoader']),
                                 yaml.safe_load(extra))

    def test_unhashable_and_unsafe_keys(self):
        self.validate('? [one, two]\n: value\n', valid=False)
        self.validate('extra: !!python/object:builtins.object {}\n', valid=False)

    def test_real_skill(self):
        result = subprocess.run([sys.executable, str(VALIDATOR), '--json', str(VALIDATOR.parents[1])],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertTrue(json.loads(result.stdout)[0]['ok'])


if __name__ == '__main__':
    unittest.main()
