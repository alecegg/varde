function if_else_if_else(a, b, c) {
  if (a) {} else if (b) {} else if (c) {} else {}
}

function else_if_body_nesting(a, b, c) {
  if (a) {} else if (b) { if (c) {} }
}

function else_body_nesting(a, b) {
  if (a) {} else { if (b) {} }
}

function nested_if_nesting(a, b) {
  if (a) { if (b) {} }
}

function loops(items) {
  for (const item of items) { if (item) {} }
}

function switch_once(value) {
  switch (value) {
    case 1: return "one";
    case 2: return "two";
    default: return "other";
  }
}

function ternary(a, b) {
  return a ? (b ? 1 : 2) : 3;
}

function catch_once(flag) {
  try { throw new Error(); } catch (error) { if (flag) { throw error; } }
}

function try_finally_zero() {
  try { work(); } finally { cleanup(); }
}

function early_return_zero(flag) {
  if (flag) return 1;
  return 0;
}

function logical_run_same(a, b, c) {
  return a && b && c;
}

function logical_run_mixed(a, b) {
  return a && b || a;
}

function logical_negated_run(a, b, c) {
  return a && !(b && c);
}

function logical_run_across_lambda(a, items) {
  return a && items.some(item => item && a);
}

function null_coalescing_zero(input, fallback) {
  let value = input?.ready ?? fallback;
  value ??= false;
  value ||= true;
  return value;
}

function lambda_nesting(flag) {
  const action = async value => { if (value) await work(); };
  action(flag);
}

function named_nested_function(flag) {
  function Inner(value) { if (value) return 1; return 0; }
  Inner(flag);
}

function class_in_method() {
  class Local {
    class_in_method_member(value) { if (value) return 1; return 0; }
  }
}

function condition_nesting(a, b, c) {
  if (a ? b : c) {}
}

function compensating_usage() {
  var foo;
  var bar = {};
  bar.myFun = function(value) { if (value) {} };
}

function compensating_usage_non_declarative() {
  var foo;
  var bar = {};
  if (foo) { work(); }
  bar.myFun = function() { if (foo) work(); };
}

function compensating_usage_callback(xs) {
  xs.forEach(x => { if (x) g(); });
}

function goto_or_labeled_jump(flag) {
  outer: while (flag) { break outer; }
}

function multi_level_break(max) {
  let total = 0;
  OUT: for (let i = 1; i <= max; ++i) {
    for (let j = 2; j < i; ++j) {
      if (i % j === 0) { continue OUT; }
    }
    total += i;
  }
  return total;
}

function recursion_direct(n) {
  return recursion_direct(n - 1);
}

function recursion_two_calls(n) {
  return recursion_two_calls(n - 1) + recursion_two_calls(n - 2);
}

class QualifiedSelf {
  recursion_qualified_self(n) { return this.recursion_qualified_self(n - 1); }
}

class OtherReceiver {
  recursion_other_receiver(other, n) {
    return other.recursion_other_receiver(n - 1);
  }
}

function recursion_in_closure(n) {
  const recur = () => recursion_in_closure(n - 1);
  return recur();
}

function recursion_same_file_cycle_a(n) {
  return recursion_same_file_cycle_b(n - 1);
}

function recursion_same_file_cycle_b(n) {
  return recursion_same_file_cycle_a(n - 1);
}

function recursion_cross_file_zero(n) {
  // The peer recursion_cross_file_peer is declared in another file.
  return OtherFile.recursion_cross_file_peer(n - 1);
}

function spec_example_small(number) {
  switch (number) {
    case 1: return "one";
    case 2: return "a couple";
    case 3: return "a few";
    default: return "lots";
  }
}

function* generator_callable(flag) {
  if (flag) yield 1;
}

var model = {
  save: function(options, callback) {
    var self = this;

    if (typeof options === 'function') {
      callback = options;
      options = {};
    }

    options || (options = {});

    self._validate(self.toJSON(), function(err) {
      if (err) {
        callback && callback.call(null, err);
        return;
      }

      self.sync(self.isNew() ? 'create' : 'update', options, function(err, response) {
        var facade = {
          options: options,
          response: response
        },
        parsed;

        if (err) {
          facade.error = err;
          facade.src = 'save';
          self.fire(EVT_ERROR, facade);
        } else {
          if (!self._saveEvent) {
            self._saveEvent = self.publish(EVT_SAVE, { preventable: false });
          }

          if (response) {
            parsed = facade.parsed = self._parse(response);
            self.setAttrs(parsed, options);
          }

          self.changed = {};
          self.fire(EVT_SAVE, facade);
        }

        callback && callback.apply(null, arguments);
      });
    });
    return self;
  }
};
