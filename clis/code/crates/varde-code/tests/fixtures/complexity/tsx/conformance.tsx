function if_else_if_else(a: boolean, b: boolean, c: boolean): JSX.Element {
  if (a) return <A />; else if (b) return <B />; else if (c) return <C />; else return <D />;
}

function else_if_body_nesting(a: boolean, b: boolean, c: boolean): JSX.Element {
  if (a) return <A />; else if (b) { if (c) return <C />; }
  return <B />;
}

function else_body_nesting(a: boolean, b: boolean): JSX.Element {
  if (a) return <A />; else { if (b) return <B />; }
  return <C />;
}

function nested_if_nesting(a: boolean, b: boolean): JSX.Element {
  if (a) { if (b) return <B />; }
  return <A />;
}

function loops(items: boolean[]): JSX.Element {
  for (const item of items) { if (item) return <Item />; }
  return <Empty />;
}

function switch_once(value: number): JSX.Element {
  switch (value) {
    case 1: return <One />;
    case 2: return <Two />;
    default: return <Other />;
  }
}

function ternary(a: boolean, b: boolean): JSX.Element {
  return a ? (b ? <One /> : <Two />) : <Three />;
}

function catch_once(flag: boolean): JSX.Element {
  try { throw new Error(); } catch (error) { if (flag) return <ErrorView />; }
  return <Okay />;
}

function try_finally_zero(): JSX.Element {
  try { work(); } finally { cleanup(); }
  return <Done />;
}

function early_return_zero(flag: boolean): JSX.Element {
  if (flag) return <One />;
  return <Zero />;
}

function logical_run_same(a: boolean, b: boolean, c: boolean): boolean {
  return a && b && c;
}

function logical_run_mixed(a: boolean): JSX.Element {
  return a && <A /> || <B />;
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

function lambda_nesting(flag: boolean): JSX.Element {
  const action = (value: boolean) => { if (value) return <Active />; };
  action(flag);
  return <Idle />;
}

function named_nested_function(flag: boolean): JSX.Element {
  function Inner(value: boolean): JSX.Element { if (value) return <Active />; return <Idle />; }
  return Inner(flag);
}

function class_in_method(): void {
  class Local {
    class_in_method_member(value: boolean): JSX.Element { if (value) return <Active />; return <Idle />; }
  }
}

function condition_nesting(a: boolean, b: boolean, c: boolean): JSX.Element {
  if (a ? b : c) return <Yes />;
  return <No />;
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

function spec_example_small(number: number): JSX.Element {
  switch (number) {
    case 1: return <One />;
    case 2: return <Couple />;
    case 3: return <Few />;
    default: return <Lots />;
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
