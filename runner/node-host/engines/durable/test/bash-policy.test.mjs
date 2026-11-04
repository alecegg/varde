import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { classifyBash } from "../tools/bash-policy.mjs";

const kind = (command) => classifyBash(command).kind;

describe("bash policy", () => {
  it("accepts relative-path discovery commands", () => {
    for (const command of [
      "pwd", "ls", "ls -la sub", "cat a.txt", "head -n 5 a.txt", "grep -rn beta .", "find . -name '*.js'",
      "ls && cat a.txt", "cat a.txt | grep alpha | wc -l", "cd sub && ls", "echo hello",
    ]) {
      assert.equal(kind(command), "discovery", command);
    }
  });

  it("classifies everything else as other", () => {
    for (const command of [
      "", "   ", "rm -rf x", "touch x", "echo hi > f", "cat a >> b", "cat < a", "ls; rm x", "ls || rm x", "ls &", "echo $(id)", "echo `id`",
      "echo $HOME", "cat /etc/passwd", "cat ~/x", "cat ../x", "ls ..", "cd /", "cd", "cd a b", "find . -exec rm {} +", "find . -delete",
      "find . -fprint out", "sort -o f a", "git status", "git log -n 3", "git diff", "git diff HEAD -- a.txt", "git show", "git grep -O x", "git -c core.fsmonitor=x status", "git push", "sort --compress-program=sh a",
      "node --test", "npm test", "python -c 1", "sed -i s/a/b/ f", "tee f", "grep x --file=/etc/passwd", "ls\nrm x", "a".repeat(2001),
    ]) {
      assert.equal(kind(command), "other", JSON.stringify(command));
    }
  });

  it("explains why", () => {
    assert.match(classifyBash("rm x").reason, /not a discovery/);
    assert.match(classifyBash("cat /etc/hosts").reason, /absolute/);
  });
});
