/*
 * Cognitive-complexity conformance fixture for C.
 *
 * Every callable named after a matrix id exercises that id; see
 * expected.toml for the hand-derived increments and spec citations. The
 * `#ifndef`/`#define` wrapper is a real include guard, and the split
 * `#ifdef __cplusplus` / `extern "C" {` pair around the body is the linkage
 * form the masked re-parse recovers.
 */
#ifndef CONFORMANCE_C_H
#define CONFORMANCE_C_H

#ifdef __cplusplus
extern "C" {
#endif

struct Ops {
    /* Same-named function-pointer field: the receiver call below must not
       bind to `recursion_other_receiver`. */
    int (*recursion_other_receiver)(struct Ops *ops, int n);
};

/* spec:175, 281-291; the file-wrapper guard adds no cognitive increment. */
int include_guard_zero(int value) {
    return value;
}

/* spec:281-291; a function between the two `extern "C"` regions gains
   nothing from them, so only its own `if` counts. */
int preproc_extern_c(int value) {
    if (value) {
        return 1;
    }
    return 0;
}

/* spec:176-179, 491-501; `if` +1, `else if` +1, `else` +1. */
int if_else_if_else(int a, int b) {
    if (a) {
        return 1;
    } else if (b) {
        return 2;
    } else {
        return 3;
    }
}

/* spec:502-518; root `if` +1, `else if` +1, and its body `if` at the root
   body's nesting adds 2. */
int else_if_body_nesting(int a, int b, int c) {
    if (a) {
        return 1;
    } else if (b) {
        if (c) {
            return 2;
        }
    }
    return 0;
}

/* spec:502-518; root `if` +1, plain `else` +1, and its body `if` at the root
   body's nesting adds 2. */
int else_body_nesting(int a, int b) {
    if (a) {
        return 1;
    } else {
        if (b) {
            return 2;
        }
    }
    return 0;
}

/* spec:510-518; outer `if` +1 and nested `if` +2. */
int nested_if_nesting(int a, int b) {
    if (a) {
        if (b) {
            return 1;
        }
    }
    return 0;
}

/* spec:491-518; `for` +1, nested `while` +2, sibling `do while` +1. */
int loops(int n) {
    int total = 0;
    for (int i = 0; i < n; i++) {
        while (total < i) {
            total++;
        }
    }
    do {
        total--;
    } while (total > n);
    return total;
}

/* spec:196-205, 491-500; the `switch` and all its cases add one point. */
int switch_once(int value) {
    switch (value) {
        case 0:
            return 0;
        case 1:
            return 1;
        case 2:
            return 2;
        default:
            return 3;
    }
}

/* spec:491-501, 510-518; outer ternary +1 and nested ternary +2. */
int ternary(int a, int b, int c) {
    return a ? (b ? 1 : 2) : c;
}

/* spec:238-243, 491-501; the `if` +1 and the early return adds 0. */
int early_return_zero(int a) {
    if (a) {
        return 1;
    }
    return 0;
}

/* spec:207-229, 491-501; one like-operator run +1. */
int logical_run_same(int a, int b, int c) {
    return a && b && c;
}

/* spec:207-229, 491-501; an `&&` run and an `||` run each add 1. */
int logical_run_mixed(int a, int b, int c) {
    return a && b || c;
}

/* spec:207-229, 254-256; the outer run +1 and the negated inner run +1. */
int logical_negated_run(int a, int b, int c) {
    return a && !(b && c);
}

/* spec:491-501, 510-518; the `if` +1 and its condition ternary +2. */
int condition_nesting(int a, int b, int c) {
    if (a ? b : c) {
        return 1;
    }
    return 0;
}

/* spec:238-243, 491-501; the `if` +1 and `goto` +1; the label adds 0. The
   label sits after the early return so the early exit itself stays 0. */
int goto_or_labeled_jump(int value) {
    if (value) {
        goto done;
    }
    return 0;
done:
    return 1;
}

/* spec:230-237, 491-501; one direct recursive function adds 1, once. */
int recursion_direct(int n) {
    return recursion_direct(n - 1);
}

/* spec:230-237, 491-501; two self-calls still add one recursion point. */
int recursion_two_calls(int n) {
    return recursion_two_calls(n - 1) + recursion_two_calls(n - 2);
}

/* spec:230-237; a same-named call through a struct function-pointer field
   does not bind to this function and adds 0. */
int recursion_other_receiver(struct Ops *ops, int n) {
    return ops->recursion_other_receiver(ops, n);
}

/* spec:230-237, 491-501; each member of a same-file cycle adds 1. */
int recursion_same_file_cycle_a(int n) {
    return recursion_same_file_cycle_b(n);
}

/* spec:230-237, 491-501; the second member of the same-file cycle. */
int recursion_same_file_cycle_b(int n) {
    return recursion_same_file_cycle_a(n);
}

/* spec:230-237; the peer `recursion_cross_file_peer` lives in another file,
   so it never binds here and the increment is 0. */
int recursion_cross_file_zero(int n) {
    return recursion_cross_file_peer(n);
}

/* spec:175, 281-291; `#if DEBUG` +1 and the nested `if` +2 (nesting 1). */
#if DEBUG
int preproc_conditional(int ready) {
    if (ready) {
        return 1;
    }
    return 0;
}
#endif

/* spec:316-327; the `switch` and all four cases combined add 1. */
int get_words(int number) {
    switch (number) {
        case 1:
            return 1;
        case 2:
            return 2;
        case 3:
            return 3;
        default:
            return 4;
    }
}

/* spec:328-339; `for` +1, nested `for` +2, nested `if` +3, `goto` +1. */
int sum_of_primes(int max) {
    int total = 0;
    for (int i = 1; i <= max; ++i) {
        for (int j = 2; j < i; ++j) {
            if (i % j == 0) {
                goto next_candidate;
            }
        }
        total += i;
next_candidate:
        continue;
    }
    return total;
}

#ifdef __cplusplus
}
#endif

#endif
