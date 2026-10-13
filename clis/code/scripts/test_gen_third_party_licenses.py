import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "gen_licenses", Path(__file__).with_name("gen-third-party-licenses.py")
)
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)


def pkg(name, license=None, license_file=None):
    return {"name": name, "version": "1.0.0", "license": license, "license_file": license_file}


class SpdxAllowedTest(unittest.TestCase):
    def test_or_passes_when_one_branch_is_allowed(self):
        self.assertTrue(gen.spdx_allowed("0BSD OR MIT"))
        self.assertTrue(gen.spdx_allowed("Apache-2.0 OR BSL-1.0"))
        self.assertTrue(gen.spdx_allowed("MIT/Apache-2.0"))

    def test_or_fails_when_no_branch_is_allowed(self):
        self.assertFalse(gen.spdx_allowed("MPL-2.0 OR GPL-3.0-only"))

    def test_and_needs_every_term_allowed(self):
        self.assertTrue(gen.spdx_allowed("MIT AND ISC"))
        self.assertFalse(gen.spdx_allowed("MIT AND MPL-2.0"))
        self.assertTrue(
            gen.spdx_allowed("ISC AND (Apache-2.0 OR ISC) AND (Apache-2.0 OR ISC OR MIT-0)")
        )
        self.assertFalse(gen.spdx_allowed("MIT AND (MPL-2.0 OR GPL-3.0-only)"))

    def test_with_exception_needs_an_allowed_base(self):
        self.assertTrue(gen.spdx_allowed("Apache-2.0 WITH LLVM-exception"))
        self.assertFalse(gen.spdx_allowed("GPL-2.0-only WITH Classpath-exception-2.0"))

    def test_malformed_expressions_raise(self):
        for expr in ["MIT OR", "(MIT", "MIT)", "MIT WITH", "AND MIT"]:
            with self.assertRaises(ValueError, msg=expr):
                gen.spdx_allowed(expr)


class CheckPolicyTest(unittest.TestCase):
    def test_permissive_packages_pass(self):
        self.assertEqual(gen.check_policy([pkg("a", "MIT OR Apache-2.0"), pkg("b", "Zlib")]), [])

    def test_missing_license_fails(self):
        self.assertEqual(len(gen.check_policy([pkg("a")])), 1)

    def test_license_file_alone_fails(self):
        violations = gen.check_policy([pkg("a", license_file="LICENSE")])
        self.assertEqual(len(violations), 1)
        self.assertIn("no SPDX license", violations[0])

    def test_unparseable_license_fails(self):
        self.assertEqual(len(gen.check_policy([pkg("a", "MIT OR")])), 1)

    def test_the_shipped_mpl_crates_fail(self):
        crates = ["cssparser", "cssparser-macros", "dtoa-short", "selectors"]
        violations = gen.check_policy([pkg(name, "MPL-2.0") for name in crates])
        self.assertEqual(len(violations), len(crates))


if __name__ == "__main__":
    unittest.main()
