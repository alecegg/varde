fn if_else_if_else(value: i32) -> i32 {
    if value == 0 { 0 }
    else if value == 1 { 1 }
    else if value == 2 { 2 }
    else { 3 }
}

fn else_if_body_nesting(value: i32) -> i32 {
    if value > 0 { 1 }
    else if value < 0 { if value == -1 { 2 } }
}

fn else_body_nesting(value: i32) -> i32 {
    if value > 0 { 1 } else { if value < 0 { 2 } }
}

fn nested_if_nesting(value: i32) -> i32 {
    if value > 0 { if value < 10 { value } }
}

fn loops(values: &[i32]) -> i32 {
    for value in values {
        while *value > 0 { if *value == 1 { return *value; } break; }
        loop { break; }
    }
    0
}

fn switch_once(value: i32) -> i32 {
    match value { 1 => 1, 2 => 2, _ => 0 }
}

fn early_return_zero(value: i32) -> i32 {
    if value > 0 { return value; }
    0
}

fn logical_run_same(a: bool, b: bool, c: bool) -> bool { a && b && c }
fn logical_run_mixed(a: bool, b: bool, c: bool) -> bool { a && b || c }
fn logical_negated_run(a: bool, b: bool, c: bool) -> bool { a && !(b && c) }
fn logical_run_across_lambda(a: bool, b: bool, c: bool) -> bool {
    a && (|| b && c)()
}

fn null_coalescing_zero(value: Option<i32>) -> i32 { value?; 0 }

fn lambda_nesting(value: i32) -> i32 {
    let nested = || { if value > 0 { let _ = value; } 0 };
    nested()
}

fn named_nested_function(value: i32) -> i32 {
    fn nested_inner(value: i32) -> i32 { if value > 0 { return value; } 0 }
    nested_inner(value)
}

fn recursion_nested_local(value: i32) -> i32 {
    fn recursive_inner(value: i32) -> i32 {
        if value <= 0 { 0 } else { recursive_inner(value - 1) }
    }
    recursive_inner(value)
}

fn class_in_method(value: i32) -> i32 {
    struct Local;
    impl Local { fn read(value: i32) -> i32 { if value > 0 { return value; } 0 } }
    Local::read(value)
}

fn if_let_else(value: Option<i32>) -> i32 {
    if let Some(value) = value { value } else { 0 }
}

fn let_else(value: Option<i32>) -> i32 {
    let Some(value) = value else { return 0; };
    value
}

fn goto_or_labeled_jump(values: &[i32]) -> i32 {
    'outer: for value in values { if *value > 0 { break 'outer; } }
    0
}

fn multi_level_break(values: &[i32]) -> i32 {
    'outer: for row in values { for value in values { if row == value { continue 'outer; } } }
    0
}

fn recursion_direct(value: i32) -> i32 { if value <= 0 { 0 } else { recursion_direct(value - 1) } }

fn recursion_two_calls(value: i32) -> i32 {
    recursion_two_calls(value - 1) + recursion_two_calls(value - 2)
}

struct Recursive;
impl Recursive {
    fn recursion_qualified_self(&self, value: i32) -> i32 { self.recursion_qualified_self(value - 1) }
    fn recursion_self_type(value: i32) -> i32 { Self::recursion_self_type(value - 1) }
    fn recursion_other_receiver(&self, other: &Recursive, value: i32) -> i32 {
        other.recursion_other_receiver(other, value - 1)
    }
}

fn recursion_in_closure(value: i32) -> i32 {
    let recurse = || recursion_in_closure(value - 1);
    recurse()
}

fn recursion_same_file_cycle_a(value: i32) -> i32 { recursion_same_file_cycle_b(value) }
fn recursion_same_file_cycle_b(value: i32) -> i32 { recursion_same_file_cycle_a(value) }

// CrossFileB is deliberately absent from this one-file fixture.
fn recursion_cross_file_zero(value: i32) -> i32 { CrossFileB(value - 1) }

fn get_words(value: i32) -> &'static str { match value { 1 => "one", 2 => "two", 3 => "three", _ => "many" } }

fn sum_primes(max: u32) -> u32 {
    let mut total = 0;
    'outer: for i in 2..max {
        for j in 2..i {
            if i % j == 0 { continue 'outer; }
        }
        total += i;
    }
    total
}

fn condition_nesting(flag: bool) -> i32 {
    if (if flag { true } else { false }) { return 1; }
    0
}
