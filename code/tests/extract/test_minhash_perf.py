from varde_code.extract.minhash import body_minhash


def test_body_minhash_returns_no_bands_for_short_input():
    assert body_minhash("def f(): return 1") is None
