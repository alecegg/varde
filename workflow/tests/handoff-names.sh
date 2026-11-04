#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
ALLOWLIST_PATH="$SCRIPT_DIR/handoff-names.allow"
source "$REPO_ROOT/core/tests/lib/repo.sh"

skill_count=0
while IFS= read -r skill; do
  [[ -f "$skill/SKILL.md" ]] && ((skill_count += 1))
done < <(skill_dirs "$REPO_ROOT")
if ((skill_count != 26)); then
  printf 'handoff-names: expected 26 skills, discovered %s.\n' "$skill_count" >&2
  exit 1
fi

scan_repo() {
  local repo_root="$1"
  local allowlist_path="$2"
  local tmp_parent="${TMPDIR:-/tmp}"
  local scan_tmp_dir raw_matches
  local grep_status=0 perl_status=0
  local skill skill_path
  local -a scan_paths=(clis skills learn memory-bank README.md core/tests/fixtures ":(glob)core/tests/*.sh" core/scripts/check-refs.sh core/docs/skills.md core/src/varde_core/skills/shared)

  while IFS= read -r skill; do
    skill_path="$(realpath "$skill")"
    scan_paths+=("${skill_path#"$repo_root"/}")
  done < <(skill_dirs "$repo_root")

  scan_tmp_dir="$(mktemp -d "$tmp_parent/varde-handoff-names.XXXXXX")" || {
    printf '%s\n' 'handoff-names: could not create a temporary directory.' >&2
    return 1
  }
  raw_matches="$scan_tmp_dir/matches"

  if git -C "$repo_root" grep -I -n -i handoff -- "${scan_paths[@]}" >"$raw_matches"; then
    :
  else
    grep_status=$?
  fi
  if ((grep_status > 1)); then
    printf 'handoff-names: git grep failed (status=%s).\n' "$grep_status" >&2
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

    BEGIN {
      $failed = 0;
      $matches = 0;
      my $file = $ENV{ALLOWLIST_PATH};
      die "handoff-names: ALLOWLIST_PATH is not set.\n" unless defined $file;
      open my $allow_file, "<", $file
        or die "handoff-names: cannot read allowlist $file: $!\n";
      my $allow_line = 0;
      while (my $line = <$allow_file>) {
        $allow_line++;
        chomp $line;
        next if $line =~ /^\s*(?:#|$)/;
        my @fields = split /\t/, $line, -1;
        die "handoff-names: allowlist line $allow_line must have four tab-separated fields.\n"
          unless @fields == 4;
        my ($category, $path_pattern, $line_pattern, $reason) = @fields;
        die "handoff-names: invalid category on allowlist line $allow_line.\n"
          unless $category =~ /\A(?:non-goal|alias|legacy-read|fixture|migration-command)\z/;
        die "handoff-names: empty path regex or reason on allowlist line $allow_line.\n"
          unless length($path_pattern) && length($reason);
        die "handoff-names: line regex must be anchored on allowlist line $allow_line.\n"
          unless length($line_pattern) && anchored_pattern($line_pattern);
        my $path_re = eval { qr{$path_pattern} };
        die "handoff-names: invalid path regex on allowlist line $allow_line: $@"
          if $@;
        my $line_re = eval { qr{$line_pattern}i };
        die "handoff-names: invalid line regex on allowlist line $allow_line: $@"
          if $@;
        push @allowlist, {
          category => $category,
          path_re => $path_re,
          line_re => $line_re,
          allow_line => $allow_line,
          used => 0,
        };
      }
      close $allow_file or die "handoff-names: could not close allowlist $file: $!\n";
    }

    chomp;
    my ($file_path, $line_number, $source_line) = split /:/, $_, 3;
    unless (defined $source_line) {
      die "handoff-names: malformed git grep result: $_\n";
    }
    $matches++;

    my $covered = 0;
    for my $entry (@allowlist) {
      next unless $file_path =~ $entry->{path_re};
      next unless $source_line =~ $entry->{line_re};
      $entry->{used} = 1;
      $covered = 1;
    }
    unless ($covered) {
      print STDERR "unallowlisted: $file_path:$line_number: $source_line\n";
      $failed = 1;
    }

    END {
      for my $entry (@allowlist) {
        next if $entry->{used};
        print STDERR "stale allowlist entry at line $entry->{allow_line}: " .
          "$entry->{category}\n";
        $failed = 1;
      }
      print "handoff-names: checked $matches match(es) against " .
        scalar(@allowlist) . " allowlist entr(y/ies).\n" unless $failed;
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

fixture_test() {
  local fixture_root fixture_allow output
  fixture_root="$(mktemp -d "${TMPDIR:-/tmp}/varde-handoff-fixture.XXXXXX")"
  trap 'rm -rf "$fixture_root"' RETURN
  mkdir -p "$fixture_root/skills" "$fixture_root/clis" "$fixture_root/memory-bank"
  printf '%s\n' 'Clean fixture.' >"$fixture_root/README.md"
  printf '%s\n' 'Clean fixture.' >"$fixture_root/skills/clean.md"
  fixture_allow="$fixture_root/handoff-names.allow"
  : >"$fixture_allow"
  git -C "$fixture_root" init -q
  git -C "$fixture_root" add README.md skills/clean.md

  printf '%s\n' 'handoff fixture violation' >"$fixture_root/skills/offending.md"
  git -C "$fixture_root" add skills/offending.md
  if output="$(scan_repo "$fixture_root" "$fixture_allow" 2>&1)"; then
    echo 'FAIL: handoff scanner accepted an offending fixture.' >&2
    return 1
  fi
  [[ "$output" == *"unallowlisted: skills/offending.md:"* ]] || {
    printf 'FAIL: handoff scanner omitted the fixture finding.\n%s\n' "$output" >&2
    return 1
  }

  git -C "$fixture_root" rm -qf skills/offending.md
  output="$(scan_repo "$fixture_root" "$fixture_allow")" || {
    printf 'FAIL: clean handoff fixture failed.\n%s\n' "$output" >&2
    return 1
  }
  [[ "$output" == *"checked 0 match(es)"* ]] || {
    printf 'FAIL: handoff scanner did not report the clean fixture result.\n%s\n' "$output" >&2
    return 1
  }
}

fixture_test
scan_repo "$REPO_ROOT" "$ALLOWLIST_PATH"
