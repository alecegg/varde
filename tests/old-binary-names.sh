#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ALLOWLIST_PATH="$REPO_ROOT/tests/old-binary-names.allow"

SELF_TEST_TMP_DIR=""

scan_repo() {
  local repo_root="$1"
  local allowlist_path="$2"
  local tmp_parent="${TMPDIR:-/tmp}"
  local scan_tmp_dir raw_matches
  local invocation_status=0 availability_status=0 perl_status=0

  scan_tmp_dir="$(mktemp -d "$tmp_parent/x.XXXX")" || {
    printf '%s\n' 'old-binary-names: could not create a temporary directory.' >&2
    return 1
  }
  raw_matches="$scan_tmp_dir/matches"

  local invocation_pattern='\b(varde-(code|workflow|toz|learn)|toz) (?!skills?\b|flow\b)(?!-)[a-z_][a-z_-]*'
  local availability_pattern='(command -v|which) (varde-(code|workflow|toz|learn)|toz)\b'

  if git -C "$repo_root" grep -nP "$invocation_pattern" \
    -- skills agents clis AGENTS.md README.md > "$raw_matches"; then
    :
  else
    invocation_status=$?
  fi
  if git -C "$repo_root" grep -nP "$availability_pattern" \
    -- skills agents clis AGENTS.md README.md >> "$raw_matches"; then
    :
  else
    availability_status=$?
  fi

  if (( invocation_status > 1 || availability_status > 1 )); then
    printf 'old-binary-names: git grep failed (invocations=%s, availability=%s).\n' \
      "$invocation_status" "$availability_status" >&2
    rm -rf "$scan_tmp_dir"
    return 1
  fi

  if ALLOWLIST_PATH="$allowlist_path" perl -ne '
    our @allowlist;
    our ($failed, $matches);

    sub anchored_pattern {
      my ($pattern) = @_;
      return 0 unless substr($pattern, 0, 1) eq "^";
      return 0 unless substr($pattern, -1, 1) eq "\$";
      my ($slashes) = $pattern =~ /(\\*)\$$/;
      return defined($slashes) && length($slashes) % 2 == 0;
    }

    sub exact_line_pattern {
      my ($line) = @_;
      my $pattern = "^";
      for my $char (split //, $line) {
        if ($char eq "\t") {
          $pattern .= "\\t";
        } elsif ($char =~ /[\\.^\$|?*+(){}\[\]]/) {
          $pattern .= "\\$char";
        } else {
          $pattern .= $char;
        }
      }
      return $pattern . "\$";
    }

    BEGIN {
      $failed = 0;
      $matches = 0;
      my $file = $ENV{ALLOWLIST_PATH};
      die "old-binary-names: ALLOWLIST_PATH is not set.\n" unless defined $file;
      open my $allow_file, "<", $file
        or die "old-binary-names: cannot read allowlist $file: $!\n";
      my $allow_line = 0;
      while (my $line = <$allow_file>) {
        $allow_line++;
        chomp $line;
        next if $line =~ /^\s*(?:#|$)/;
        my @fields = split /\t/, $line, -1;
        die "old-binary-names: allowlist line $allow_line must have four tab-separated fields.\n"
          unless @fields == 4;
        my ($class, $path_pattern, $line_pattern, $reason) = @fields;
        die "old-binary-names: invalid class on allowlist line $allow_line.\n"
          unless $class =~ /\A[ABCDE]\z/;
        die "old-binary-names: empty path regex or reason on allowlist line $allow_line.\n"
          unless length($path_pattern) && length($reason);
        if (($class eq "B" || $class eq "E") &&
            (!length($line_pattern) || !anchored_pattern($line_pattern))) {
          die "old-binary-names: class $class line regex must be nonempty and anchored with ^ and \$.\n";
        }
        my $path_re = eval { qr{$path_pattern} };
        die "old-binary-names: invalid path regex on allowlist line $allow_line: $@"
          if $@;
        my $line_re;
        if (length $line_pattern) {
          $line_re = eval { qr{$line_pattern} };
          die "old-binary-names: invalid line regex on allowlist line $allow_line: $@"
            if $@;
        }
        push @allowlist, {
          class => $class,
          path_pattern => $path_pattern,
          path_re => $path_re,
          line_pattern => $line_pattern,
          line_re => $line_re,
          reason => $reason,
          allow_line => $allow_line,
          used => 0,
        };
      }
      close $allow_file or die "old-binary-names: could not close allowlist $file: $!\n";
    }

    chomp;
    my ($path, $line_number, $source_line) = split /:/, $_, 3;
    unless (defined $source_line) {
      die "old-binary-names: malformed git grep result: $_\n";
    }
    $matches++;

    my $covered = 0;
    for my $entry (@allowlist) {
      next unless $path =~ $entry->{path_re};
      next if defined($entry->{line_re}) && $source_line !~ $entry->{line_re};
      if (($entry->{class} eq "B" || $entry->{class} eq "E") &&
          $entry->{line_pattern} ne exact_line_pattern($source_line)) {
        print STDERR "old-binary-names: class $entry->{class} line regex is not an exact source line " .
          "(allowlist line $entry->{allow_line}, $path:$line_number).\n";
        $failed = 1;
        next;
      }
      $entry->{used} = 1;
      $covered = 1;
    }
    unless ($covered) {
      print STDERR "unallowlisted: $path:$line_number: $source_line\n";
      $failed = 1;
    }

    END {
      for my $entry (@allowlist) {
        next if $entry->{used};
        print STDERR "stale allowlist entry at line $entry->{allow_line}: " .
          "$entry->{path_pattern}\n";
        $failed = 1;
      }
      print "old-binary-names: checked $matches match(es) against " .
        scalar(@allowlist) . " allowlist entry/entries.\n" unless $failed;
      exit($failed ? 1 : 0);
    }
  ' "$raw_matches"; then
    perl_status=0
  else
    perl_status=$?
  fi

  rm -rf "$scan_tmp_dir"
  return "$perl_status"
}

self_test() {
  local tmp_parent="${TMPDIR:-/tmp}"
  SELF_TEST_TMP_DIR="$(mktemp -d "$tmp_parent/x.XXXX")"
  trap 'rm -rf "$SELF_TEST_TMP_DIR"' EXIT

  local fixture_repo="$SELF_TEST_TMP_DIR/repo"
  local fixture_allow="$fixture_repo/tests/old-binary-names.allow"
  local hook_line='const HOOK_NAME: &str = "varde-workflow hook";'
  local second_hook_line='// See varde-workflow check for legacy identity.'
  local e_hook_line='// Retained legacy name: varde-toz query.'
  mkdir -p "$fixture_repo/skills" "$fixture_repo/agents" \
    "$fixture_repo/clis/workflow/src" "$fixture_repo/tests"
  printf '%s\n' 'Repository rules.' > "$fixture_repo/AGENTS.md"
  printf '%s\n' 'Repository readme.' > "$fixture_repo/README.md"
  printf '%s\n' 'No old command here.' > "$fixture_repo/agents/empty.md"
  printf '%s\n' 'varde-workflow review check' 'which toz' \
    > "$fixture_repo/skills/violation.md"
  printf '%s\n' "$hook_line" > "$fixture_repo/clis/workflow/src/hook.rs"
  printf '%s\n' "$second_hook_line" > "$fixture_repo/clis/workflow/src/other.rs"
  printf '%s\n' "$e_hook_line" > "$fixture_repo/clis/workflow/src/evidence.rs"
  printf '%s\t%s\t%s\t%s\n' \
    'B' '^clis/workflow/src/hook[.]rs$' \
    '^const HOOK_NAME: &str = "varde-workflow hook";$' \
    'Legacy hook identity pending cutover.' > "$fixture_allow"
  printf '%s\t%s\t%s\t%s\n' \
    'B' '^clis/workflow/src/other[.]rs$' \
    '^// See varde-workflow check for legacy identity\.$' \
    'Legacy module comment pending cutover.' >> "$fixture_allow"
  printf '%s\t%s\t%s\t%s\n' \
    'E' '^clis/workflow/src/evidence[.]rs$' \
    '^// Retained legacy name: varde-toz query\.$' \
    'Permanent non-invoking legacy-name record.' >> "$fixture_allow"

  git -C "$fixture_repo" init -q
  git -C "$fixture_repo" add -- AGENTS.md README.md agents/empty.md \
    skills/violation.md clis/workflow/src/hook.rs clis/workflow/src/other.rs \
    clis/workflow/src/evidence.rs \
    tests/old-binary-names.allow

  local output status
  if output="$(scan_repo "$fixture_repo" "$fixture_allow" 2>&1)"; then
    printf '%s\n' 'FAIL: self-test expected an unallowlisted invocation to fail.' >&2
    return 1
  fi
  if [[ "$output" != *"unallowlisted: skills/violation.md:"* ]]; then
    printf '%s\n' 'FAIL: self-test did not report its planted violation.' "$output" >&2
    return 1
  fi

  rm "$fixture_repo/skills/violation.md"
  if output="$(scan_repo "$fixture_repo" "$fixture_allow" 2>&1)"; then
    :
  else
    status=$?
    printf 'FAIL: covered identity line failed with exit %s.\n%s\n' \
      "$status" "$output" >&2
    return 1
  fi
  if [[ "$output" != *"checked 3 match(es) against 3 allowlist entry/entries"* ]]; then
    printf '%s\n' 'FAIL: self-test did not count all covered matches.' "$output" >&2
    return 1
  fi

  printf '%s\t%s\t\t%s\n' 'C' '^skills/missing[.]md$' \
    'Deliberately stale entry for self-test.' >> "$fixture_allow"
  if output="$(scan_repo "$fixture_repo" "$fixture_allow" 2>&1)"; then
    printf '%s\n' 'FAIL: self-test expected a stale allowlist entry to fail.' >&2
    return 1
  fi
  if [[ "$output" != *"stale allowlist entry"* ]]; then
    printf '%s\n' 'FAIL: self-test did not report its stale allowlist entry.' "$output" >&2
    return 1
  fi

  printf '%s\t%s\t\t%s\n' 'B' '^clis/workflow/src/hook[.]rs$' \
    'Legacy hook identity pending cutover.' > "$SELF_TEST_TMP_DIR/allowlist.empty-line"
  mv "$SELF_TEST_TMP_DIR/allowlist.empty-line" "$fixture_allow"
  if output="$(scan_repo "$fixture_repo" "$fixture_allow" 2>&1)"; then
    printf '%s\n' 'FAIL: self-test expected an empty class-B line regex to fail.' >&2
    return 1
  fi
  if [[ "$output" != *"class B line regex"* ]]; then
    printf '%s\n' 'FAIL: self-test did not reject an empty class-B line regex.' "$output" >&2
    return 1
  fi

  printf '%s\t%s\t%s\t%s\n' 'B' '^clis/workflow/src/hook[.]rs$' \
    'const HOOK_NAME: &str = "varde-workflow hook";$' \
    'Unanchored identity line for self-test.' > "$SELF_TEST_TMP_DIR/allowlist.unanchored"
  mv "$SELF_TEST_TMP_DIR/allowlist.unanchored" "$fixture_allow"
  if output="$(scan_repo "$fixture_repo" "$fixture_allow" 2>&1)"; then
    printf '%s\n' 'FAIL: self-test expected an unanchored class-B line regex to fail.' >&2
    return 1
  fi
  if [[ "$output" != *"class B line regex"* ]]; then
    printf '%s\n' 'FAIL: self-test did not reject an unanchored class-B line regex.' "$output" >&2
    return 1
  fi

  printf '%s\t%s\t%s\t%s\n' 'E' '^clis/workflow/src/evidence[.]rs$' \
    '// Retained legacy name: varde-toz query\.$' \
    'Unanchored class-E line for self-test.' > "$SELF_TEST_TMP_DIR/allowlist.e-unanchored"
  mv "$SELF_TEST_TMP_DIR/allowlist.e-unanchored" "$fixture_allow"
  if output="$(scan_repo "$fixture_repo" "$fixture_allow" 2>&1)"; then
    printf '%s\n' 'FAIL: self-test expected an unanchored class-E line regex to fail.' >&2
    return 1
  fi
  if [[ "$output" != *"class E line regex"* ]]; then
    printf '%s\n' 'FAIL: self-test did not reject an unanchored class-E line regex.' "$output" >&2
    return 1
  fi

  rm "$fixture_repo/clis/workflow/src/other.rs"
  rm "$fixture_repo/clis/workflow/src/evidence.rs"
  printf '%s\t%s\t%s\t%s\n' \
    'B' '^clis/workflow/src/hook[.]rs$' \
    '^const HOOK_NAME: &str = "varde-workflow hook";$' \
    'Legacy hook identity pending cutover.' > "$fixture_allow"
  printf '%s\n' \
    "$hook_line varde-toz query" \
    > "$fixture_repo/clis/workflow/src/hook.rs"
  if output="$(scan_repo "$fixture_repo" "$fixture_allow" 2>&1)"; then
    printf '%s\n' 'FAIL: self-test expected an appended invocation to be reported.' >&2
    return 1
  fi
  if [[ "$output" != *"unallowlisted: clis/workflow/src/hook.rs:"* ]]; then
    printf '%s\n' 'FAIL: appending an invocation to an allowed identity line was not reported.' "$output" >&2
    return 1
  fi

  rm "$fixture_repo/clis/workflow/src/hook.rs"
  : > "$fixture_allow"
  if output="$(scan_repo "$fixture_repo" "$fixture_allow" 2>&1)"; then
    :
  else
    status=$?
    printf 'FAIL: no-match git grep status was rejected (exit %s).\n%s\n' \
      "$status" "$output" >&2
    return 1
  fi

  printf '%s\n' 'old-binary-names: self-test passed.'
}

if [[ "${1:-}" == "--self-test" ]]; then
  self_test
  exit
fi

if [[ "$#" -ne 0 ]]; then
  printf 'Usage: %s [--self-test]\n' "${BASH_SOURCE[0]}" >&2
  exit 2
fi

scan_repo "$REPO_ROOT" "$ALLOWLIST_PATH"
