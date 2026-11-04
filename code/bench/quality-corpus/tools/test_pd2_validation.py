# ruff: noqa: S101
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pd2_validation as pv

MODULE = '''
import os
LIMIT = 3

def one(a):
    """doc"""
    return a + LIMIT

def two(b, c=1):
    if b:
        return c
    return 0

class K:
    def three(self, d):
        for x in d:
            print(x)

    def four(self):
        return os.getcwd()
'''


def test_inline_to_monolith_gives_one_function_with_all_bodies():
    code = pv.inline_to_monolith(MODULE)
    tree = ast.parse(code)
    funcs = pv.all_functions(tree)
    assert [f.name for f in funcs] == ["process_module"]
    assert pv.parameter_names(funcs) == ["a", "b", "c", "self", "d"]
    assert "doc" not in code


def test_inline_needs_four_nest_free_functions():
    assert pv.inline_to_monolith("def a():\n    pass\n") is None
    nested = MODULE + "\ndef five():\n    def inner():\n        pass\n"
    assert len(pv.module_functions(ast.parse(nested))) == 5
    assert pv.inline_to_monolith(nested) is not None


def test_tidy_few_function_filter():
    assert pv.is_tidy_few_function("def load_config(path):\n    return path\n")
    assert not pv.is_tidy_few_function("def f(x):\n    return x\n")
    assert not pv.is_tidy_few_function(MODULE)
    assert not pv.is_tidy_few_function("x = 1\n")


def test_max_nesting_counts_branch_depth():
    src = (
        "def f(a):\n    if a:\n        for i in a:\n"
        "            while i:\n                pass\n"
    )
    assert pv.max_nesting(src) == 3


def test_pick_by_hash_caps_per_origin_and_is_deterministic():
    cands = {f"k{i}": ("repo" + str(i % 2), str(i).encode()) for i in range(10)}
    first = pv.pick_by_hash(cands, 4, 2)
    assert first == pv.pick_by_hash(cands, 4, 2)
    origins = [cands[k][0] for k in first]
    assert len(first) == 4 and origins.count("repo0") == 2
