#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(dirname "${BASH_SOURCE[0]}")"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
ALLOWLIST_PATH="$SCRIPT_DIR/handoff-names.allow"

scan_repo() {
  local repo_root="$1"
  local allowlist_path="$2"
  local tmp_parent="${TMPDIR:-/tmp}"
  local scan_tmp_dir raw_matches
  local grep_status=0 perl_status=0

  scan_tmp_dir="$(mktemp -d "$tmp_parent/varde-handoff-names.XXXXXX")" || {
    printf '%s\n' 'handoff-names: could not create a temporary directory.' >&2
    return 1
  }
  raw_matches="$scan_tmp_dir/matches"

  if git -C "$repo_root" grep -I -n -i handoff -- clis skills memory-bank README.md >"$raw_matches"; then
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

scan_repo "$REPO_ROOT" "$ALLOWLIST_PATH"
