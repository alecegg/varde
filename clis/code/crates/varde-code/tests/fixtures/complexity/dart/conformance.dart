// Cognitive complexity conformance fixture for Dart.

int if_else_if_else(int x) {
  if (x == 0) return 0;
  else if (x == 1) return 1;
  else return 2;
}

int else_if_body_nesting(int x) {
  if (x == 0) return 0;
  else if (x == 1) {
    if (x > 0) return 1;
  }
  return 2;
}

int else_body_nesting(int x) {
  if (x == 0) return 0;
  else {
    if (x > 0) return 1;
  }
  return 2;
}

int nested_if_nesting(int x) {
  if (x > 0) {
    if (x > 1) return x;
  }
  return 0;
}

int loops(List<int> values) {
  for (final value in values) {
    while (value > 0) {
      if (value == 1) return value;
    }
  }
  return 0;
}

int switch_once(int x) {
  final statement = switch (x) {
    1 => 10,
    2 => 20,
    _ => 0,
  };
  switch (x) {
    case 1: return statement;
    case 2: return 20;
    default: return 0;
  }
}

int ternary(int x) => x > 0 ? 1 : 0;

int catch_once(int x) {
  try {
    if (x > 0) throw StateError('x');
  } on StateError {
    if (x == 1) return 1;
  } on FormatException catch (error) {
    if (error.message.isNotEmpty) return 2;
  }
  return 0;
}

int try_finally_zero() {
  try {
    return 1;
  } finally {
    final ignored = 0;
  }
}

int early_return_zero(int x) {
  if (x > 0) return 1;
  return 0;
}

bool logical_run_same(bool a, bool b, bool c) => a && b && c;

bool logical_run_mixed(bool a, bool b, bool c) => a && b || c;

bool logical_negated_run(bool a, bool b, bool c) => a && !(b && c);

bool logical_run_across_lambda(bool a, List<int> values) =>
    a && values.any((value) => value > 0 && value < 10);

int? null_coalescing_zero(int? value, int? backup) {
  var current = value ?? backup;
  current ??= 1;
  final length = current?.toString().length;
  final result = <int>[current ?? 0]..add(length ?? 0);
  return result.first;
}

int lambda_nesting(List<int> values) {
  values.forEach((value) {
    if (value > 0) print(value);
  });
  return 0;
}

int named_nested_function(int x) {
  int inner(int value) {
    if (value > 0) return value;
    return 0;
  }
  return inner(x);
}

int condition_nesting(bool a, bool b, bool c) {
  if (a && b || c) return 1;
  return 0;
}

int collection_comprehension(List<int> values, bool enabled) => [
      if (enabled)
        for (final value in values)
          value,
    ].length;

int goto_or_labeled_jump(int n) {
  outer:
  while (n > 0) {
    break outer;
  }
  return n;
}

int multi_level_break(int n) {
  outer:
  for (var i = 0; i < n; i++) {
    for (var j = 0; j < n; j++) {
      if (i + j > n) continue outer;
    }
  }
  return n;
}

class RecursionCases {
  int recursion_direct(int n) {
    if (n > 0) return recursion_direct(n - 1);
    return 0;
  }

  int recursion_two_calls(int n) {
    if (n <= 0) return 0;
    recursion_two_calls(n - 1);
    return recursion_two_calls(n - 2);
  }

  int recursion_qualified_self(int n) {
    if (n > 0) return this.recursion_qualified_self(n - 1);
    return 0;
  }

  int recursion_other_receiver(RecursionCases other, int n) =>
      other.recursion_other_receiver(other, n - 1);

  int recursion_in_closure(int n) {
    final recurse = () {
      return recursion_in_closure(n - 1);
    };
    return n > 0 ? recurse() : 0;
  }

  int recursion_same_file_cycle_a(int n) => recursion_same_file_cycle_b(n - 1);

  int recursion_same_file_cycle_b(int n) => recursion_same_file_cycle_a(n - 1);

  // Cross-file peer is intentionally absent from this fixture.
  int recursion_cross_file_zero(int n) => OtherFile.recursion_cross_file_peer(n - 1);
}

int spec_example_small(int x) {
  switch (x) {
    case 1: return 1;
    case 2: return 2;
    case 3: return 3;
    default: return 0;
  }
}

int sumOfPrimes(int max) {
  var total = 0;
  OUT:
  for (var i = 1; i <= max; ++i) {
    for (var j = 2; j < i; ++j) {
      if (i % j == 0) continue OUT;
    }
    total += i;
  }
  return total;
}
