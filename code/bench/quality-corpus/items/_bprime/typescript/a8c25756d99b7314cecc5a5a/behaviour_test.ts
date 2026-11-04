import { groupByLength } from "./solution.ts";

function check(expected: string, actual: Record<number, string[]>): void {
  const rendered = JSON.stringify(actual);
  if (rendered !== expected) {
    throw new Error(`expected ${expected} but got ${rendered}`);
  }
}

check('{"3":["the","fox"],"5":["quick","brown"]}', groupByLength("the quick brown fox"));
check("{}", groupByLength(""));
check('{"1":["a"]}', groupByLength("a"));
check('{"2":["ab","cd","ef"]}', groupByLength("ab cd ef"));
check('{"3":["one","two"],"5":["three"]}', groupByLength("one two three"));
check('{"2":["hi"],"5":["there"]}', groupByLength("  hi  there "));
check('{"1":["b","d"],"3":["ccc"],"4":["aaaa"]}', groupByLength("aaaa b ccc d"));
check('{"4":["same","same"]}', groupByLength("same same"));
check('{"1":["x"],"2":["yy"],"3":["zzz"]}', groupByLength("x yy zzz"));
check('{"2":["gh"],"6":["abcdef"]}', groupByLength("abcdef gh"));
