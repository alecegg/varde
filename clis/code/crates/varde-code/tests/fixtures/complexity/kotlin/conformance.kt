fun if_else_if_else(a: Boolean, b: Boolean, c: Boolean) {
    if (a) { work() } else if (b) { work() } else if (c) { work() } else { work() }
}

fun else_if_body_nesting(a: Boolean, b: Boolean, c: Boolean) {
    if (a) { work() } else if (b) { if (c) { work() } }
}

fun else_body_nesting(a: Boolean, b: Boolean) {
    if (a) { work() } else { if (b) { work() } }
}

fun nested_if_nesting(a: Boolean, b: Boolean) {
    if (a) { if (b) { work() } }
}

fun loops(items: List<Boolean>) {
    for (item in items) {
        while (item) { if (item) break }
    }
}

fun switch_once(number: Int): String = when (number) {
    1 -> "one"
    2 -> "two"
    else -> "other"
}

fun catch_once(flag: Boolean) {
    try { error("failure") } catch (error: IllegalStateException) { if (flag) work() }
}

fun try_finally_zero() {
    try { work() } finally { cleanup() }
}

fun early_return_zero(flag: Boolean) {
    if (flag) return
    return
}

fun logical_run_same(a: Boolean, b: Boolean, c: Boolean) {
    if (a && b && c) work()
}

fun logical_run_mixed(a: Boolean, b: Boolean, c: Boolean) {
    if (a && b || c) work()
}

fun logical_negated_run(a: Boolean, b: Boolean, c: Boolean) {
    if (a && !(b && c)) work()
}

fun logical_run_across_lambda(a: Boolean, items: List<Item>) {
    if (a && items.any { item -> item.ready && item.valid }) work()
}

fun null_coalescing_zero(value: String?, fallback: String): Int {
    return value?.length ?: fallback.length
}

fun lambda_nesting(items: List<Boolean>) {
    items.forEach { item -> if (item) work() }
}

fun named_nested_function(flag: Boolean) {
    fun inner(value: Boolean) { if (value) work() }
    inner(flag)
}

fun class_in_method(flag: Boolean) {
    class Local {
        fun local_member(value: Boolean) { if (value) work() }
    }
    val local = Local()
    val anonymous = object {
        fun anonymous_object_member(value: Boolean) { if (value) work() }
    }
    local.local_member(flag)
    anonymous.anonymous_object_member(flag)
}

fun condition_nesting(a: Boolean, b: Boolean, c: Boolean) {
    if (a && (b || c)) work()
}

fun goto_or_labeled_jump(flag: Boolean) {
    outer@ while (flag) { break@outer }
}

fun multi_level_break(max: Int) {
    outer@ for (i in 1..max) {
        for (j in 2 until i) {
            if (i % j == 0) continue@outer
        }
    }
}

fun recursion_direct(n: Int) { recursion_direct(n - 1) }

fun recursion_two_calls(n: Int) {
    recursion_two_calls(n - 1)
    recursion_two_calls(n - 2)
}

class QualifiedSelf {
    fun recursion_qualified_self(n: Int) { this.recursion_qualified_self(n - 1) }
}

class OtherReceiver {
    fun recursion_other_receiver(other: OtherReceiver, n: Int) {
        other.recursion_other_receiver(other, n - 1)
    }
}

class OverloadDelegate {
    fun recursion_overload_delegate() { recursion_overload_delegate(1) }
    fun recursion_overload_delegate(n: Int) { work() }
}

fun recursion_in_closure(n: Int) {
    val recur = { recursion_in_closure(n - 1) }
    recur()
}

fun recursion_same_file_cycle_a(n: Int) { recursion_same_file_cycle_b(n - 1) }
fun recursion_same_file_cycle_b(n: Int) { recursion_same_file_cycle_a(n - 1) }

fun recursion_cross_file_zero(n: Int) {
    // recursion_cross_file_peer is defined in another file.
    OtherFile.recursion_cross_file_peer(n - 1)
}

fun extension_scope_case(flag: Boolean) {
    if (flag) work()
}

fun String.extension_function_scope_case(flag: Boolean) {
    if (flag) work()
}

fun labeled_lambda_return_zero(values: List<Int>) {
    values.forEach skip@ { value ->
        if (value < 0) return@skip
        work()
    }
}

class ObjectScopedRecursion {
    fun object_scoped_recursion(n: Int) {
        if (n > 0) this.object_scoped_recursion(n - 1)
    }
}

object SingletonScopedRecursion {
    fun singleton_scoped_recursion(n: Int) {
        if (n > 0) this.singleton_scoped_recursion(n - 1)
    }
}

fun spec_example_small(number: Int): String = when (number) {
    1 -> "one"
    2 -> "a couple"
    3 -> "a few"
    else -> "lots"
}

fun sumOfPrimes(max: Int): Int {
    var total = 0
    OUT@ for (i in 1..max) {
        for (j in 2 until i) {
            if (i % j == 0) continue@OUT
        }
        total += i
    }
    return total
}

class Item(val ready: Boolean, val valid: Boolean)
