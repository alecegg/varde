function if_else_if_else(a: boolean, b: boolean, c: boolean): void {
  if (a) {} else if (b) {} else if (c) {} else {}
}

function else_if_body_nesting(a: boolean, b: boolean, c: boolean): void {
  if (a) {} else if (b) { if (c) {} }
}

function else_body_nesting(a: boolean, b: boolean): void {
  if (a) {} else { if (b) {} }
}

function nested_if_nesting(a: boolean, b: boolean): void {
  if (a) { if (b) {} }
}

function loops(items: boolean[]): void {
  for (const item of items) { if (item) {} }
}

function switch_once(value: number): string {
  switch (value) {
    case 1: return "one";
    case 2: return "two";
    default: return "other";
  }
}

function ternary(a: boolean, b: boolean): number {
  return a ? (b ? 1 : 2) : 3;
}

function catch_once(flag: boolean): void {
  try { throw new Error(); } catch (error) { if (flag) { throw error; } }
}

function try_finally_zero(): void {
  try { work(); } finally { cleanup(); }
}

function early_return_zero(flag: boolean): number {
  if (flag) return 1;
  return 0;
}

function logical_run_same(a: boolean, b: boolean, c: boolean): boolean {
  return a && b && c;
}

function logical_run_mixed(a: boolean, b: boolean): boolean {
  return a && b || a;
}

function logical_negated_run(a: boolean, b: boolean, c: boolean): boolean {
  return a && !(b && c);
}

function logical_run_across_lambda(a: boolean, items: boolean[]): boolean {
  return a && items.some(item => item && a);
}

function null_coalescing_zero(input: {ready?: boolean} | undefined, fallback: boolean | undefined): boolean {
  let value = input?.ready ?? fallback;
  value ??= false;
  value ||= true;
  value &&= false;
  return value;
}

function lambda_nesting(flag: boolean): void {
  const action = (value: boolean) => { if (value) {} };
  action(flag);
}

function named_nested_function(flag: boolean): void {
  function Inner(value: boolean): void { if (value) {} }
  Inner(flag);
}

function class_in_method(): void {
  class Local {
    class_in_method_member(value: boolean): number { if (value) return 1; return 0; }
  }
}

function condition_nesting(a: boolean, b: boolean, c: boolean): void {
  if (a ? b : c) {}
}

function compensating_usage(): void {
  let foo: unknown;
  const bar: any = {};
  bar.myFun = function compensating_usage_inner(value: boolean): void { if (value) {} };
}

function compensating_usage_non_declarative(): void {
  let foo: unknown;
  const bar: any = {};
  if (foo) { work(); }
  bar.myFun = function compensating_usage_non_declarative_inner(): void { if (foo) work(); };
}

function compensating_usage_callback(items: boolean[]): void {
  items.forEach(item => { if (item) work(); });
}

function goto_or_labeled_jump(flag: boolean): void {
  outer: while (flag) { break outer; }
}

function multi_level_break(max: number): number {
  let total = 0;
  OUT: for (let i = 1; i <= max; ++i) {
    for (let j = 2; j < i; ++j) {
      if (i % j === 0) { continue OUT; }
    }
    total += i;
  }
  return total;
}

function recursion_direct(n: number): number {
  return recursion_direct(n - 1);
}

function recursion_two_calls(n: number): number {
  return recursion_two_calls(n - 1) + recursion_two_calls(n - 2);
}

class QualifiedSelf {
  recursion_qualified_self(n: number): number { return this.recursion_qualified_self(n - 1); }
}

class OtherReceiver {
  recursion_other_receiver(other: {recursion_other_receiver: (n: number) => number}, n: number): number {
    return other.recursion_other_receiver(n - 1);
  }
}

function recursion_in_closure(n: number): number {
  const recur = () => recursion_in_closure(n - 1);
  return recur();
}

function recursion_same_file_cycle_a(n: number): number {
  return recursion_same_file_cycle_b(n - 1);
}

function recursion_same_file_cycle_b(n: number): number {
  return recursion_same_file_cycle_a(n - 1);
}

function recursion_cross_file_zero(n: number): number {
  // The peer recursion_cross_file_peer is declared in another file.
  return OtherFile.recursion_cross_file_peer(n - 1);
}

function spec_example_small(number: number): string {
  switch (number) {
    case 1: return "one";
    case 2: return "a couple";
    case 3: return "a few";
    default: return "lots";
  }
}

function my_method_example(): number {
  if (firstCondition) {
    for (const item of items) {
      while (hasNext(item)) { step(item); }
    }
  }
  try { work(); }
  catch (error) { if (recover(error)) { retry(); } }
  return 0;
}
