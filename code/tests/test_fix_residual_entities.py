from varde_code.extract.entity import extract_file


def test_preprocessor_scanning_covers_csharp_and_haskell() -> None:
    source = "#if FEATURE\nclass Fixture {}\n#endif\n"
    csharp = extract_file("Fixture.cs", source, "csharp")
    haskell_source = "{-# LANGUAGE CPP #-}\n#if FEATURE\nmodule Fixture where\n#endif\n"
    haskell = extract_file("Fixture.hs", haskell_source, "haskell")

    assert [
        entity.name for entity in csharp.entities if entity.name == "preproc_if"
    ] == ["preproc_if"]
    assert [
        entity.name for entity in haskell.entities if entity.name == "preproc_if"
    ] == ["preproc_if"]
