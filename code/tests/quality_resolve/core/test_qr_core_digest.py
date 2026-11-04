from varde_code.quality_resolve import digest_for_file, edges_for_file, prepare


def changed(before, after, files):
    return {
        path
        for path in files
        if digest_for_file(before, path) != digest_for_file(after, path)
    }


def test_local_digest_changes_only_for_edited_file():
    files = {"a.py": {"functions": [{"name": "one"}]}, "b.py": {}}
    edited = {**files, "a.py": {"functions": [{"name": "two"}]}}
    assert changed(prepare(files, files), prepare(edited, edited), files) == {"a.py"}


def test_imported_and_receiver_digest_follow_import_target():
    files = {
        "main.py": {
            "imports": [{"module": "lib", "name": "work"}],
            "call_sites": [{"caller": "m", "name": "work"}],
        },
        "recv.py": {
            "imports": [{"module": "lib", "alias": "client"}],
            "call_sites": [
                {"caller": "r", "name": "client.send", "receiver": "client"}
            ],
        },
        "lib.py": {"functions": [{"name": "work"}, {"name": "send"}]},
        "other.py": {},
    }
    edited = {**files, "lib.py": {"functions": [{"name": "changed"}]}}
    before, after = prepare(files, files), prepare(edited, edited)
    assert changed(before, after, files) == {"main.py", "recv.py", "lib.py"}


def test_namespace_callable_invalidation_tracks_only_dependent_files():
    files = {
        "a/Main.java": {
            "package": "same",
            "functions": [{"id": "caller", "name": "call", "owner": "A"}],
            "call_sites": [{"caller": "caller", "name": "work", "arity": 0}],
        },
        "a/Peer.java": {
            "package": "same",
            "functions": [{"id": "work", "name": "work", "owner": "A"}],
        },
        "b/Other.java": {"package": "else"},
        "plain.py": {},
    }
    edited = {
        **files,
        "a/Peer.java": {"package": "same", "functions": []},
    }
    before, after = prepare(files, files), prepare(edited, edited)
    assert changed(before, after, edited) == {"a/Main.java", "a/Peer.java"}


def test_namespace_callable_digest_ignores_unrelated_owner():
    files = {
        "a/Main.java": {
            "package": "same",
            "functions": [{"id": "caller", "name": "call", "owner": "A"}],
            "call_sites": [{"caller": "caller", "name": "work", "arity": 0}],
        },
        "a/Peer.java": {"package": "same"},
        "b/Other.java": {
            "package": "else",
            "functions": [{"id": "other-work", "name": "work", "owner": "B"}],
        },
    }
    added = {
        **files,
        "a/Peer.java": {
            "package": "same",
            "functions": [{"id": "work", "name": "work", "owner": "B"}],
        },
    }
    assert changed(prepare(files, files), prepare(added, added), added) == {
        "a/Peer.java"
    }


def test_namespace_type_invalidation_tracks_only_dependent_files():
    files = {
        "a/Main.java": {"package": "same"},
        "a/Peer.java": {"package": "same"},
        "b/Other.java": {"package": "else"},
        "plain.py": {},
    }
    edited = {
        **files,
        "a/Peer.java": {
            "package": "same",
            "types": [{"name": "Widget", "kind": "class"}],
        },
    }
    before, after = prepare(files, files), prepare(edited, edited)
    assert changed(before, after, edited) == {"a/Peer.java"}


def test_imported_type_without_methods_invalidates_non_namespace_receiver():
    facts = {
        "main.py": {
            "imports": [{"module": "lib", "alias": "mod"}],
            "call_sites": [{"caller": "caller", "name": "f", "receiver_text": "mod"}],
        },
        "lib.py": {},
    }
    edited = {**facts, "lib.py": {"types": [{"name": "Widget", "kind": "class"}]}}
    before, after = prepare(facts, facts), prepare(edited, edited)
    assert digest_for_file(before, "main.py") != digest_for_file(after, "main.py")


def test_manifest_digest_is_explicit_input_and_scoped_to_subtree():
    files = {"crate/src/a.rs": {}, "other/src/b.rs": {}, "main.go": {}}
    old = {"crate/Cargo.toml": "[package]\nname='a'"}
    new = {"crate/Cargo.toml": "[package]\nname='b'"}
    before = prepare(files, files, old)
    after = prepare(files, files, new)
    assert changed(before, after, files) == {"crate/src/a.rs"}


def test_unrelated_edit_does_not_change_digest_and_is_deterministic():
    facts = {"a.py": {"functions": [{"name": "a"}]}, "b.py": {}}
    first = prepare(facts, facts)
    second = prepare(dict(reversed(list(facts.items()))), facts)
    assert digest_for_file(first, "a.py") == digest_for_file(second, "a.py")
    edited = {**facts, "b.py": {"functions": [{"name": "unrelated"}]}}
    assert digest_for_file(first, "a.py") == digest_for_file(
        prepare(edited, edited), "a.py"
    )


def test_unresolved_classification_tracks_project_callable_names_in_other_files():
    facts = {"caller.py": {"call_sites": [{"name": "foo"}]}, "lib.py": {}}
    added = {**facts, "lib.py": {"functions": [{"name": "foo"}]}}
    before, after = prepare(facts, facts), prepare(added, added)
    assert edges_for_file(before, "caller.py")[0]["kind"] == "external"
    assert edges_for_file(after, "caller.py")[0]["kind"] == "opaque"
    assert changed(before, after, facts) == {
        "caller.py",
        "lib.py",
    }


def test_import_digest_tracks_resolution_fields_and_type_target_path():
    facts = {
        "main.py": {
            "imports": [{"module": "lib", "name": "work"}],
            "call_sites": [{"name": "work", "arity": 1}],
        },
        "lib.py": {"functions": [{"id": "f1", "name": "work", "params": 1}]},
    }
    changed_id = {
        **facts,
        "lib.py": {"functions": [{"id": "f2", "name": "work", "params": 1}]},
    }
    changed_arity = {
        **facts,
        "lib.py": {"functions": [{"id": "f1", "name": "work", "params": 0}]},
    }
    before, after_id = prepare(facts, facts), prepare(changed_id, changed_id)
    assert edges_for_file(before, "main.py")[0]["callee"] == "f1"
    assert edges_for_file(after_id, "main.py")[0]["callee"] == "f2"
    assert changed(before, after_id, facts) == {"main.py", "lib.py"}
    after_arity = prepare(changed_arity, changed_arity)
    assert edges_for_file(after_arity, "main.py")[0]["kind"] == "opaque"
    assert changed(before, after_arity, facts) == {"main.py", "lib.py"}
    type_facts = {
        "src/Main.java": {
            "package": "app",
            "call_sites": [{"name": "Widget", "arity": 0}],
            "functions": [
                {"id": "ctor", "name": "<init>", "owner": "Widget", "params": 0}
            ],
        },
        "src/Types.java": {
            "package": "app",
            "types": [
                {"id": "t1", "name": "Widget", "kind": "class", "path": "src/Main.java"}
            ],
        },
    }
    changed_type = {
        **type_facts,
        "src/Main.java": {
            "package": "app",
            "call_sites": [{"name": "Widget", "arity": 0}],
            "functions": [
                {"id": "ctor", "name": "<init>", "owner": "Other", "params": 0}
            ],
        },
        "src/Types.java": {
            "package": "app",
            "types": [
                {"id": "t2", "name": "Widget", "kind": "class", "path": "src/Main.java"}
            ],
        },
    }
    before, after = prepare(type_facts, type_facts), prepare(changed_type, changed_type)
    assert edges_for_file(before, "src/Main.java")[0]["callee"] == "ctor"
    assert edges_for_file(after, "src/Main.java")[0]["callee"] == "t2"
    moved_type = {
        **changed_type,
        "src/Types.java": {
            "package": "app",
            "types": [
                {"id": "t2", "name": "Widget", "kind": "class", "path": "src/Else.java"}
            ],
        },
    }
    moved = prepare(moved_type, moved_type)
    assert edges_for_file(moved, "src/Main.java")[0]["kind"] == "external"
    assert changed(before, after, type_facts) == {"src/Main.java"}
    assert changed(after, moved, changed_type) == {"src/Main.java"}


def test_receiver_digest_tracks_target_details_without_plain_call():
    facts = {
        "main.py": {
            "imports": [{"module": "lib", "alias": "client"}],
            "call_sites": [{"name": "client.send", "receiver": "client"}],
        },
        "lib.py": {"functions": [{"id": "f1", "name": "send", "params": 0}]},
    }
    edited = {
        **facts,
        "lib.py": {"functions": [{"id": "f2", "name": "send", "params": 0}]},
    }
    before, after = prepare(facts, facts), prepare(edited, edited)
    assert edges_for_file(before, "main.py")[0]["callee"] == "f1"
    assert edges_for_file(after, "main.py")[0]["callee"] == "f2"
    assert changed(before, after, facts) == {"main.py", "lib.py"}


def test_language_scoped_contexts_and_manifests():
    facts = {"a.swift": {}, "b.java": {}, "c.go": {}, "d.py": {}}
    java_added = {**facts, "b.java": {"functions": [{"name": "new"}]}}
    assert changed(prepare(facts, facts), prepare(java_added, java_added), facts) == {
        "b.java"
    }
    old = {"go.mod": "module example/old", "Cargo.toml": "[package]\nname='old'"}
    new = {"go.mod": "module example/new", "Cargo.toml": "[package]\nname='new'"}
    assert changed(prepare(facts, facts, old), prepare(facts, facts, new), facts) == {
        "c.go"
    }
    nested = {
        "crate/Cargo.toml": "[workspace]\nmembers=[]",
        "go.mod": "module example/old",
    }
    nested_new = {**nested, "crate/Cargo.toml": "[workspace]\nmembers=['x']"}
    cargo_files = {"crate/src/lib.rs": {}, "other.py": {}}
    assert changed(
        prepare(cargo_files, cargo_files, nested),
        prepare(cargo_files, cargo_files, nested_new),
        cargo_files,
    ) == {"crate/src/lib.rs"}


def test_import_candidates_and_non_importing_file_dependencies():
    facts = {"main.py": {"imports": [{"module": "newmod"}]}, "other.py": {}}
    added = {**facts, "newmod.py": {}}
    assert changed(prepare(facts, facts), prepare(added, added), facts) == {"main.py"}
    edit = {**facts, "other.py": {"functions": [{"name": "unrelated"}]}}
    assert changed(prepare(facts, facts), prepare(edit, edit), facts) == {"other.py"}


def test_digest_rejects_missing_path_and_sorts_every_input_order():
    facts = {
        "a.py": {
            "imports": [{"module": "z"}, {"module": "x"}],
            "functions": [{"name": "z"}, {"name": "x"}],
        },
        "b.py": {},
    }
    reverse = {
        "a.py": {
            "imports": list(reversed(facts["a.py"]["imports"])),
            "functions": list(reversed(facts["a.py"]["functions"])),
        },
        "b.py": {},
    }
    assert digest_for_file(prepare(facts, facts), "a.py") == digest_for_file(
        prepare(dict(reversed(list(facts.items()))), reverse), "a.py"
    )
    try:
        digest_for_file(prepare(facts, facts), "missing.py")
    except KeyError:
        pass
    else:
        raise AssertionError("missing paths must not produce a shared digest")
