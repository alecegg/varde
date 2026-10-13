#!/usr/bin/env python3
"""Generate THIRD-PARTY-LICENSES.md — the attribution bundle for the crates
that `varde` release binaries statically link (including every bundled
tree-sitter grammar).

Reproducible and tool-free: it reads the *actual* link-time dependency set
(`cargo tree -e normal,build`, so dev-only crates are excluded) and each
dependency's own license text from the local registry, then emits a grouped,
deduplicated Markdown document. Run after the crate has been built/fetched so
all sources are present under the cargo registry.

    python3 scripts/gen-third-party-licenses.py            # write the bundle
    python3 scripts/gen-third-party-licenses.py --check    # policy gate only

Writes THIRD-PARTY-LICENSES.md at the repo root. The MIT/BSD/ISC/Apache-2.0
licenses in the tree all require reproducing their copyright + license notice
when redistributing in binary form; this file is that reproduction.

`--check` skips generation (needs only `cargo metadata`, no crate sources) and
fails if any link-time dependency carries a license outside the permissive
allow-list below — the tool-free equivalent of a `cargo-deny` license gate,
so a future copyleft or unlicensed dependency breaks CI instead of shipping.
"""

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CRATE = "varde"
TARGETS = [
    "x86_64-unknown-linux-gnu",
    "aarch64-unknown-linux-gnu",
    "aarch64-apple-darwin",
]

# SPDX identifiers permitted in a redistributed binary. Every one is a
# permissive (attribution-only) license — no copyleft (GPL/LGPL/MPL/AGPL/EPL/
# CDDL). Extend deliberately, never to silence a real copyleft pull-in.
ALLOWED_LICENSES = {
    "MIT", "Apache-2.0", "LLVM-exception", "BSD-2-Clause", "BSD-3-Clause",
    "ISC", "CC0-1.0", "Unlicense", "Unicode-3.0", "Unicode-DFS-2016", "Zlib",
}

# Common names crates use for their license/notice files.
LICENSE_GLOBS = [
    "LICENSE*", "LICENCE*", "COPYING*", "COPYRIGHT*", "NOTICE*", "UNLICENSE*",
]


def run(*args: str) -> str:
    return subprocess.check_output(list(args), cwd=ROOT, text=True)


def link_time_crates() -> set[tuple[str, str]]:
    """The (name, version) set that links into the shipped `varde` binary on
    any release target: runtime and build dependencies, no dev-only crates."""
    crates: set[tuple[str, str]] = set()
    for target in TARGETS:
        out = run(
            "cargo", "tree", "--locked", "-p", CRATE, "--target", target,
            "-e", "normal,build", "--prefix", "none", "--no-dedupe",
        )
        for line in out.splitlines():
            toks = line.split()
            if len(toks) < 2:
                continue
            name = toks[0]
            ver = next((t for t in toks[1:] if t.startswith("v") and t[1:2].isdigit()), None)
            if name and ver:
                crates.add((name, ver.lstrip("v")))
    return crates


def license_files(pkg: dict) -> dict[str, str]:
    """Every license/notice text shipped in the crate's source dir, plus any
    explicit `license-file` from its manifest."""
    crate_dir = Path(pkg["manifest_path"]).parent
    found: dict[str, str] = {}
    lf = pkg.get("license_file")
    if lf:
        p = crate_dir / lf
        if p.is_file():
            found[p.name] = p.read_text(errors="replace")
    for glob in LICENSE_GLOBS:
        for p in sorted(crate_dir.glob(glob)):
            if p.is_file() and p.name not in found:
                found[p.name] = p.read_text(errors="replace")
    return found


def spdx_allowed(expr: str) -> bool:
    """Whether an SPDX expression can be satisfied using only ALLOWED_LICENSES:
    an OR needs one allowed branch, an AND needs every term allowed, and a WITH
    exception is accepted when its base id is allowed. `A/B` is `A OR B`.
    Raises ValueError for an expression that does not parse."""
    tokens = re.findall(r"\(|\)|[^\s()]+", expr.replace("/", " OR "))
    pos = 0

    def peek() -> str:
        return tokens[pos] if pos < len(tokens) else ""

    def take() -> str:
        nonlocal pos
        token = peek()
        pos += 1
        return token

    def parse_or() -> bool:
        result = parse_and()
        while peek() == "OR":
            take()
            result = parse_and() or result
        return result

    def parse_and() -> bool:
        result = parse_term()
        while peek() == "AND":
            take()
            result = parse_term() and result
        return result

    def parse_term() -> bool:
        if peek() == "(":
            take()
            result = parse_or()
            if take() != ")":
                raise ValueError(f"unbalanced parentheses in {expr!r}")
            return result
        token = take()
        if token in ("", ")", "OR", "AND", "WITH"):
            raise ValueError(f"unexpected {token!r} in {expr!r}")
        if peek() == "WITH":
            take()
            if take() in ("", "(", ")", "OR", "AND", "WITH"):
                raise ValueError(f"missing exception id in {expr!r}")
        return token in ALLOWED_LICENSES

    result = parse_or()
    if pos != len(tokens):
        raise ValueError(f"trailing {tokens[pos]!r} in {expr!r}")
    return result


def check_policy(pkgs: list[dict]) -> list[str]:
    """Violations: a link-time crate with no SPDX `license` (a `license_file`
    alone is not accepted) or whose expression cannot be satisfied with
    ALLOWED_LICENSES."""
    violations: list[str] = []
    for p in pkgs:
        label = f"{p['name']} {p['version']}"
        expr = p.get("license")
        if not expr:
            violations.append(f"{label}: no SPDX license declared")
            continue
        try:
            allowed = spdx_allowed(expr)
        except ValueError as error:
            violations.append(f"{label}: unparseable license: {error}")
            continue
        if not allowed:
            violations.append(f"{label}: no allowed option in {expr!r}")
    return violations


def main() -> int:
    check_only = "--check" in sys.argv[1:]

    meta = json.loads(run("cargo", "metadata", "--format-version", "1", "--locked"))
    workspace = set(meta["workspace_members"])
    by_key = {(p["name"], p["version"]): p for p in meta["packages"]}

    wanted = link_time_crates()
    pkgs = [
        by_key[k] for k in wanted
        if k in by_key and by_key[k]["id"] not in workspace
    ]
    pkgs.sort(key=lambda p: (p["name"].lower(), p["version"]))

    violations = check_policy(pkgs)
    if violations:
        print("license policy violations (see ALLOWED_LICENSES):", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 1
    if check_only:
        print(f"license policy OK: {len(pkgs)} link-time deps, all permissive")
        return 0

    # blob-hash -> [text, filename, [crate labels]] so identical license texts
    # (e.g. the verbatim Apache-2.0 body) are printed once, attributed to all.
    blobs: dict[str, list] = {}
    rows: list[tuple[str, str, str, str]] = []
    missing: list[str] = []
    for p in pkgs:
        name, ver = p["name"], p["version"]
        lic = p.get("license") or (
            f'file: {p["license_file"]}' if p.get("license_file") else "UNSPECIFIED"
        )
        rows.append((name, ver, lic, p.get("repository") or ""))
        texts = license_files(p)
        if not texts:
            missing.append(f"{name} {ver} ({lic})")
            continue
        for fn, txt in texts.items():
            h = hashlib.sha256(txt.encode("utf-8", "replace")).hexdigest()
            blobs.setdefault(h, [txt, fn, []])[2].append(f"{name} {ver}")

    lines: list[str] = []
    lines.append("# Third-party licenses")
    lines.append("")
    lines.append(
        "`varde` release binaries statically link the Rust crates listed below, "
        "including every bundled tree-sitter grammar. Their licenses are "
        "permissive (MIT / Apache-2.0 / BSD / ISC / Unicode-3.0 / Unlicense / "
        "CC0) and require reproducing the copyright and license notices when "
        "redistributed in binary form. Those notices are included verbatim here."
    )
    lines.append("")
    lines.append(
        "Generated by `scripts/gen-third-party-licenses.py` from `Cargo.lock` "
        "(link-time deps only, dev-dependencies excluded). Do not edit by hand."
    )
    lines.append("")
    lines.append(f"## Dependencies ({len(pkgs)})")
    lines.append("")
    lines.append("| Crate | Version | License | Source |")
    lines.append("|---|---|---|---|")
    for n, v, l, r in rows:
        lines.append(f"| {n} | {v} | {l} | {r} |")
    if missing:
        lines.append("")
        lines.append("## Crates without a bundled license file")
        lines.append("")
        lines.append(
            "These declare an SPDX license but ship no license text in the "
            "crate; the SPDX identifier in the table above governs:"
        )
        lines.append("")
        for m in missing:
            lines.append(f"- {m}")
    lines.append("")
    lines.append("## License texts")
    for _h, (txt, fn, crates) in sorted(blobs.items(), key=lambda kv: kv[1][2][0].lower()):
        who = ", ".join(sorted(set(crates)))
        lines.append("")
        lines.append(f"### {fn} — {who}")
        lines.append("")
        lines.append("```")
        lines.append(txt.rstrip("\n"))
        lines.append("```")

    (ROOT / "THIRD-PARTY-LICENSES.md").write_text("\n".join(lines) + "\n")
    print(
        f"wrote THIRD-PARTY-LICENSES.md: {len(pkgs)} link-time deps, "
        f"{len(blobs)} unique license texts, {len(missing)} without bundled text"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
