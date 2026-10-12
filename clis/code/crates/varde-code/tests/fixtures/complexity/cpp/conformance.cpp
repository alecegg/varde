/*
 * Cognitive-complexity conformance fixture for C++.
 *
 * Every callable named after a matrix id exercises that id; see expected.toml
 * for the hand-derived increments and spec citations. The `#ifndef`/`#define`
 * wrapper is a real include guard, and the split `#ifdef __cplusplus` /
 * `extern "C" {` pair around the body is the linkage form the masked re-parse
 * recovers.
 */
#ifndef CONFORMANCE_CPP_H
#define CONFORMANCE_CPP_H

#ifdef __cplusplus
extern "C" {
#endif

int include_guard_zero(int value) {
    return value;
}

int preproc_extern_c(int value) {
    if (value) {
        return 1;
    }
    return 0;
}

int if_else_if_else(bool a, bool b) {
    if (a) {
        return 1;
    } else if (b) {
        return 2;
    } else {
        return 3;
    }
}

int else_if_body_nesting(bool a, bool b, bool c) {
    if (a) {
        return 1;
    } else if (b) {
        if (c) {
            return 2;
        }
    }
    return 0;
}

int else_body_nesting(bool a, bool b) {
    if (a) {
        return 1;
    } else {
        if (b) {
            return 2;
        }
    }
    return 0;
}

int nested_if_nesting(bool a, bool b) {
    if (a) {
        if (b) {
            return 1;
        }
    }
    return 0;
}

int loops(const std::vector<int>& values, int limit) {
    int total = 0;
    for (int value : values) {
        while (total < value) {
            total += 1;
        }
    }
    do {
        total -= 1;
    } while (total > limit);
    return total;
}

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

int ternary(bool a, bool b, bool c) {
    return a ? (b ? 1 : 2) : c;
}

int catch_once(bool a, bool b) {
    try {
        risky();
    } catch (const Error& first) {
        if (a && b) {
            return 1;
        }
    }
    return 0;
}

int early_return_zero(bool a) {
    if (a) {
        return 1;
    }
    return 0;
}

int logical_run_same(bool a, bool b, bool c) {
    return a && b && c;
}

int logical_run_mixed(bool a, bool b, bool c) {
    return a && b || c;
}

int logical_negated_run(bool a, bool b, bool c) {
    return a && !(b && c);
}

int logical_run_across_lambda(bool a, bool b, bool p, bool q) {
    return consume(a && b, [&] { return p && q; });
}

int lambda_nesting(bool ready) {
    auto callback = [&] {
        if (ready) {
            return 1;
        }
        return 0;
    };
    return callback();
}

int class_in_method(int value) {
    struct Local {
        int g(int v) {
            if (v) {
                return 1;
            }
            return 0;
        }
    };
    return Local().g(value);
}

int condition_nesting(bool condition, bool left, bool right) {
    if (condition ? left : right) {
        return 1;
    }
    return 0;
}

int goto_or_labeled_jump(int value) {
    if (value) {
        goto done;
    }
    return 0;
done:
    return 1;
}

int recursion_direct(int n) {
    return recursion_direct(n - 1);
}

int recursion_two_calls(int n) {
    return recursion_two_calls(n - 1) + recursion_two_calls(n - 2);
}

class Recursion
{
public:
    int recursion_qualified_self(int n) {
        return this->recursion_qualified_self(n - 1);
    }

    /* Extra row: the `Type::f` form of a qualified self-call. */
    int recursion_qualified_type(int n) {
        return Recursion::recursion_qualified_type(n - 1);
    }
};

class Peer
{
public:
    int recursion_other_receiver(int n) {
        return other->recursion_other_receiver(n);
    }

private:
    Peer* other;
};

int recursion_overload_delegate(int n) {
    return recursion_overload_delegate(n, 0);
}

int recursion_overload_delegate(int n, int extra) {
    return n + extra;
}

int recursion_in_closure(int n) {
    auto callback = [&] { return recursion_in_closure(n - 1); };
    return callback();
}

int recursion_same_file_cycle_a(int n) {
    return recursion_same_file_cycle_b(n);
}

int recursion_same_file_cycle_b(int n) {
    return recursion_same_file_cycle_a(n);
}

/* The peer `recursion_cross_file_peer` lives in another file. */
int recursion_cross_file_zero(int n) {
    return recursion_cross_file_peer(n);
}

#if DEBUG
int preproc_conditional(bool ready) {
    auto callback = [&] {
        if (ready) {
            return 1;
        }
        return 0;
    };
    return callback();
}
#endif

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

struct Runner
{
    int run_out_of_line(int n);
};

/* Extra row: an out-of-line definition resolves its owner from the
   qualified declarator, so the unqualified self-call still binds. */
int Runner::run_out_of_line(int n) {
    return run_out_of_line(n - 1);
}

struct Starter
{
    int value;

    Starter(int start) : value(start) {}
};

struct Holder
{
    ~Holder() {}
};

struct Counter
{
    int value;

    Counter operator+(const Counter& rhs) {
        if (rhs.value) {
            return rhs;
        }
        return *this;
    }
};

template <typename T>
T identity(T value) {
    return value;
}

int my_method(bool condition1, bool condition2) {
    try {
        if (condition1) {
            for (int i = 0; i < 10; i++) {
                while (condition2) {
                    work();
                }
            }
        }
    } catch (const Error& error) {
        if (condition2) {
            return 1;
        }
    }
    return 0;
}

#ifdef __cplusplus
}
#endif

#endif
