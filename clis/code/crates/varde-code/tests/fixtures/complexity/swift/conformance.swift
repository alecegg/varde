func if_else_if_else(_ a: Bool, _ b: Bool, _ c: Bool) {
    if a { run() } else if b { run() } else if c { run() } else { run() }
}

func else_if_body_nesting(_ a: Bool, _ b: Bool, _ c: Bool) {
    if a { run() } else if b { if c { run() } }
}

func else_body_nesting(_ possible: Int?, _ flag: Bool) {
    if let value = possible { run(value) } else { if flag { run() } }
}

func nested_if_nesting(_ a: Bool, _ b: Bool) {
    if a { if b { run() } }
}

func loops(_ values: [Int]) {
    for value in values { while value > 0 { if value == 1 { run() } } }
}

func switch_once(_ value: Int) {
    switch value { case 0: run(); case 1: run(); default: run() }
}

func ternary(_ a: Bool, _ b: Bool) -> Int {
    return a ? (b ? 1 : 2) : 3
}

func catch_once(_ flag: Bool) {
    do { try risky() } catch { if flag { recover() } }
}

func try_finally_zero(_ flag: Bool) {
    defer { cleanup() }
    if flag { return }
}

func early_return_zero(_ flag: Bool) {
    if flag { return }
}

func logical_run_same(_ a: Bool, _ b: Bool, _ c: Bool) -> Bool { a && b && c }

func logical_run_mixed(_ a: Bool, _ b: Bool, _ c: Bool) -> Bool { a && b || c }

func logical_negated_run(_ a: Bool, _ b: Bool, _ c: Bool) {
    if a && !(b && c) { run() }
}

func logical_run_across_lambda(_ a: Bool, _ b: Bool, _ c: Bool) -> Bool {
    a && b && [true].contains { value in value && c }
}

func null_coalescing_zero(_ first: String?, _ second: String) -> String {
    return first ?? second
}

func lambda_nesting(_ flag: Bool) {
    let work = { if flag { run() } }
    work()
}

func named_nested_function(_ flag: Bool) {
    func nested() { if flag { run() } }
    nested()
}

func class_in_method(_ flag: Bool) {
    class Local {
        func inner() { if flag { run() } }
    }
    Local().inner()
}

func condition_nesting(_ a: Bool, _ b: Bool) {
    if (a ? b : false) { run() }
}

func goto_or_labeled_jump(_ flag: Bool) {
    outer: while true {
        if flag { break outer }
    }
}

func multi_level_break(_ stop: Bool) {
    outer: for _ in 0..<2 {
        while true {
            if stop { break outer }
        }
    }
}

func get_words(_ value: Int) -> Int {
    switch value {
    case 0: return 0
    case 1: return 1
    case 2: return 2
    default: return 3
    }
}

func sum_primes(_ limit: Int) {
    outer: for value in 2...limit {
        for divisor in 2..<value {
            if value % divisor == 0 { continue outer }
        }
    }
}

func my_method(_ first: Bool, _ second: Bool) {
    do {
        if first {
            run()
            for _ in 0..<1 {
                while second { try risky() }
            }
        }
    } catch {
        if second { recover() }
    }
}

class RecursionCases {
    func recursion_overload_delegate(_ value: Int) {
        recursion_overload_delegate(value, enabled: true)
    }

    func recursion_overload_delegate(_ value: Int, enabled: Bool) {
        if enabled { consume(value) }
    }

    func recursion_in_closure(_ value: Int) {
        let again = { self.recursion_in_closure(value - 1) }
        again()
    }

    func recursion_cross_file_zero(_ value: Int) {
        // recursion_cross_file_peer intentionally is absent from this one-file fixture.
        recursion_cross_file_peer(value - 1)
    }

    func recursion_direct(_ value: Int) {
        if value > 0 { recursion_direct(value - 1) }
    }

    func recursion_two_calls(_ value: Int) {
        if value > 0 { recursion_two_calls(value - 1); recursion_two_calls(value - 2) }
    }

    func recursion_qualified_self(_ value: Int) {
        if value > 0 { self.recursion_qualified_self(value - 1) }
    }

    func recursion_other_receiver(_ other: RecursionCases, _ value: Int) {
        other.recursion_other_receiver(other, value - 1)
    }

    func recursion_same_file_cycle(_ value: Int) {
        recursion_same_file_cycle_peer(value)
    }

    func recursion_same_file_cycle_peer(_ value: Int) {
        recursion_same_file_cycle(value)
    }

    static func recursion_qualified_type(_ value: Int) {
        if value > 0 { RecursionCases.recursion_qualified_type(value - 1) }
    }
}

func preproc_conditional(_ flag: Bool) {
#if DEBUG
    let work = { if flag { run() } }
#endif
}

#if DEBUG
let buildConfig = 1
#elseif RELEASE
let buildConfig = 2
#else
let buildConfig = 3
#endif

func guard_else(_ flag: Bool) {
    guard flag else { return }
    run()
}
