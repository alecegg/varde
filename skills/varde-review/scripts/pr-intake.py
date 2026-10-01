#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Read a GitHub PR's unresolved review threads and failing checks as JSON.

Usage: pr-intake.py <pr> [--repo-root DIR]

<pr> is a PR number, branch, or URL. Every `gh` call runs with GH_HOST set to
the PR URL's host, or else the host of `gh repo view --json url`. The script
only reads: it does not check out, write, push, or reply.

Output (stdout, exit 0):
  {pr: {number, url, host, owner, repo, head_ref, head_oid},
   threads: [{id, path, line, original_line, is_outdated,
              comments: [{author, body, url}]}],
   failing_checks: [...], conversation_comments: [{author, body, url}]}

Failure prints {"error": <name>, "message": <text>} and exits:
  1 usage
  2 preflight failed: gh_missing, auth, not_open, head_mismatch
  3 API or malformed output
"""
import json
import os
import re
import shutil
import subprocess
import sys
from urllib.parse import urlparse

THREADS_QUERY = """
query Threads($owner: String!, $repo: String!, $pr: Int!, $endCursor: String) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $pr) {
      reviewThreads(first: 100, after: $endCursor) {
        nodes {
          id isResolved isOutdated path line originalLine
          comments(first: 100) {
            nodes { body url author { login } }
            pageInfo { hasNextPage endCursor }
          }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""

MORE_COMMENTS_QUERY = """
query More($id: ID!, $endCursor: String) {
  node(id: $id) {
    ... on PullRequestReviewThread {
      comments(first: 100, after: $endCursor) {
        nodes { body url author { login } }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""

# gh's exact stderr when a PR has no checks (pkg/cmd/pr/checks/checks.go at
# v2.101.0). Anything else on a failed call, such as auth or API errors, is not
# "no checks".
NO_CHECKS_RE = re.compile(r"^no checks reported on the '[^'\n]*' branch\s*$")


class Fail(Exception):
    def __init__(self, code, error, message):
        self.code, self.error, self.message = code, error, message


def gh(args, env, cwd):
    return subprocess.run(
        ["gh"] + args, env=env, cwd=cwd, capture_output=True, text=True
    )


def gh_json(args, env, cwd, what):
    proc = gh(args, env, cwd)
    if proc.returncode != 0:
        raise Fail(3, "api", "%s failed: %s" % (what, proc.stderr.strip()))
    try:
        return json.loads(proc.stdout)
    except ValueError:
        raise Fail(3, "api", "%s returned malformed JSON" % what)


def resolve_host(pr, env, cwd):
    if re.match(r"^https?://", pr):
        host = urlparse(pr).hostname
        if host:
            return host
    proc = gh(["repo", "view", "--json", "url"], env, cwd)
    if proc.returncode != 0:
        if gh(["auth", "status"], env, cwd).returncode != 0:
            raise Fail(2, "auth", "gh auth status failed: " + proc.stderr.strip())
        raise Fail(3, "api", "gh repo view failed: %s" % proc.stderr.strip())
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        raise Fail(3, "api", "gh repo view returned malformed JSON")
    host = urlparse(str(data.get("url", ""))).hostname
    if not host:
        raise Fail(3, "api", "gh repo view returned no url")
    return host


def comment_view(c):
    return {
        "author": (c.get("author") or {}).get("login"),
        "body": c.get("body"),
        "url": c.get("url"),
    }


def fetch_threads(owner, repo, number, env, cwd):
    pages = gh_json(
        ["api", "graphql", "--paginate", "--slurp",
         "-F", "pr=%d" % number, "-f", "owner=" + owner, "-f", "repo=" + repo,
         "-f", "query=" + THREADS_QUERY],
        env, cwd, "review thread query")
    if not isinstance(pages, list):
        raise Fail(3, "api", "review thread query returned no page list")
    threads = []
    for page in pages:
        try:
            nodes = page["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
        except (KeyError, TypeError):
            raise Fail(3, "api", "review thread page has an unexpected shape")
        if not isinstance(nodes, list) or not all(isinstance(n, dict) for n in nodes):
            raise Fail(3, "api", "review thread nodes are not a list of objects")
        threads.extend(nodes)
    return threads


def thread_comments(thread, env, cwd):
    try:
        comments = thread["comments"]
        nodes = list(comments["nodes"])
        info = comments["pageInfo"]
        thread_id = thread["id"]
    except (KeyError, TypeError):
        raise Fail(3, "api", "review thread has an unexpected shape")
    while info.get("hasNextPage"):
        data = gh_json(
            ["api", "graphql", "-f", "id=" + thread_id,
             "-f", "endCursor=" + str(info.get("endCursor")),
             "-f", "query=" + MORE_COMMENTS_QUERY],
            env, cwd, "thread comment query")
        try:
            more = data["data"]["node"]["comments"]
        except (KeyError, TypeError):
            raise Fail(3, "api", "thread comment page has an unexpected shape")
        try:
            nodes.extend(more["nodes"])
            info = more["pageInfo"]
        except (KeyError, TypeError):
            raise Fail(3, "api", "thread comment page has an unexpected shape")
    return [comment_view(c) for c in nodes]


def fetch_failing_checks(pr, env, cwd):
    proc = gh(["pr", "checks", pr, "--json",
               "name,state,bucket,link,description,workflow"], env, cwd)
    try:
        checks = json.loads(proc.stdout)
    except ValueError:
        checks = None
    if isinstance(checks, list) and proc.returncode in (0, 1, 8):
        return [c for c in checks if c.get("bucket") == "fail"]
    if checks is None and proc.returncode != 0 and not proc.stdout.strip() \
            and NO_CHECKS_RE.match(proc.stderr.strip()):
        return []
    raise Fail(3, "api", "gh pr checks failed (exit %d): %s"
               % (proc.returncode, proc.stderr.strip() or "malformed output"))


def intake(pr, repo_root):
    if shutil.which("gh") is None:
        raise Fail(2, "gh_missing", "gh is not on PATH")
    env = dict(os.environ)
    env.pop("GH_HOST", None)
    host = resolve_host(pr, env, repo_root)
    env["GH_HOST"] = host

    if gh(["auth", "status", "-h", host], env, repo_root).returncode != 0:
        raise Fail(2, "auth", "gh auth status failed for " + host)

    view = gh_json(["pr", "view", pr, "--json",
                    "number,url,state,headRefName,headRefOid,comments"],
                   env, repo_root, "gh pr view")
    if view.get("state") != "OPEN":
        raise Fail(2, "not_open", "PR state is %s" % view.get("state"))
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root,
                          capture_output=True, text=True).stdout.strip()
    if head != view.get("headRefOid"):
        raise Fail(2, "head_mismatch", "HEAD %s is not the PR head %s"
                   % (head or "(none)", view.get("headRefOid")))

    pr_url = view.get("url")
    parts = urlparse(str(pr_url or "")).path.strip("/").split("/")
    if len(parts) < 4 or parts[2] != "pull":
        raise Fail(3, "api", "unexpected PR url %s" % pr_url)
    owner, repo = parts[0], parts[1]
    number = view.get("number")
    if not isinstance(number, int):
        raise Fail(3, "api", "gh pr view returned no PR number")

    threads = []
    for t in fetch_threads(owner, repo, number, env, repo_root):
        if t.get("isResolved"):
            continue
        if not isinstance(t.get("id"), str) or not t.get("id"):
            raise Fail(3, "api", "review thread has no id")
        threads.append({
            "id": t["id"],
            "path": t.get("path"),
            "line": t.get("line"),
            "original_line": t.get("originalLine"),
            "is_outdated": bool(t.get("isOutdated")),
            "comments": thread_comments(t, env, repo_root),
        })

    return {
        "pr": {"number": number, "url": pr_url, "host": host,
               "owner": owner, "repo": repo,
               "head_ref": view.get("headRefName"),
               "head_oid": view.get("headRefOid")},
        "threads": threads,
        "failing_checks": fetch_failing_checks(pr, env, repo_root),
        "conversation_comments": [comment_view(c) for c in view.get("comments", [])],
    }


def main(argv):
    args = argv[1:]
    repo_root = os.getcwd()
    if len(args) == 3 and args[1] == "--repo-root":
        repo_root, args = args[2], args[:1]
    if len(args) != 1 or args[0].startswith("-"):
        print(json.dumps({"error": "usage",
                          "message": "pr-intake.py <pr> [--repo-root DIR]"}))
        return 1
    try:
        print(json.dumps(intake(args[0], repo_root), indent=2))
        return 0
    except Fail as e:
        print(json.dumps({"error": e.error, "message": e.message}))
        return e.code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
