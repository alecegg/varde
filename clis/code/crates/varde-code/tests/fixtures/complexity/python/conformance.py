def if_else_if_else(value):
    if value == 1:
        return 1
    elif value == 2:
        return 2
    else:
        return 0


def else_if_body_nesting(value):
    if value == 1:
        return 1
    elif value == 2:
        if value > 0:
            return 2
    return 0


def else_body_nesting(value):
    if value:
        return 1
    else:
        if value < 0:
            return -1
    return 0


def nested_if_nesting(value):
    if value:
        if value > 1:
            return 2
    return 0


def loops(items):
    for item in items:
        while item:
            if item > 3:
                break
        else:
            pass
    else:
        pass
    return 0


def switch_once(value):
    match value:
        case 1:
            return "one"
        case 2:
            return "two"
        case _:
            return "many"


def ternary(value):
    return "large" if value > 10 else "small"


def catch_once(operation):
    try:
        return operation()
    except ValueError:
        return 0
    except TypeError:
        return 1


def try_finally_zero(operation):
    try:
        return operation()
    else:
        return True
    finally:
        cleanup()


def early_return_zero(value):
    if value:
        return 1
    return 0


def logical_run_same(a, b, c):
    return a and b and c


def logical_run_mixed(a, b, c):
    return a and b or c


def logical_negated_run(a, b, c):
    if a and not (b and c):
        return 0
    return 1


def logical_run_across_lambda(a, b, c):
    callback = lambda: a and b
    return (a and b) and callback()


def lambda_nesting(value):
    callback = lambda: 1 if value else 0
    return callback()


def class_in_method(value):
    class Local:
        pass
    return value


def condition_nesting(a, b, c):
    if a and b or c:
        return 1
    return 0


def a_decorator(a, b):
    def inner(func):
        if b:
            print(b)
        func()
    return inner


def not_a_decorator(a, b):
    my_var = a * b
    def non_decorator_inner(func):
        if b:
            print(b)
        func()
    return non_decorator_inner


def decorator_generator(a):
    def generator(func):
        def decorator(func):
            if a:
                print(a)
            return func()
        return decorator
    return generator


def compensating_usage_callback(xs):
    xs.sort(key=lambda x: g(x) if x else 0)


def recursion_direct(value):
    if value:
        return recursion_direct(value - 1) + recursion_same_file_cycle(value - 1)
    return 0


def recursion_two_calls(value):
    if value > 1:
        return recursion_two_calls(value - 1) + recursion_two_calls(value - 2)
    return value


class RecursiveMethods:
    def recursion_qualified_self(self, value):
        if value:
            return self.recursion_qualified_self(value - 1)
        return 0

    def recursion_other_receiver(self, other, value):
        if value:
            return other.recursion_other_receiver(other, value - 1)
        return 0


def recursion_in_closure(value):
    marker = value
    def named_nested_function(remaining):
        if remaining:
            return named_nested_function(remaining - 1)
        return 0
    return named_nested_function(value)


def recursion_same_file_cycle(value):
    if value:
        return recursion_direct(value - 1)
    return 0


def recursion_cross_file_zero(value):
    # recursion_external_peer is defined in another file, absent from this fixture.
    if value:
        return recursion_external_peer(value - 1)
    return 0


def comprehension_or_query(items, ready, fallback):
    return [item for item in items if ready and fallback or item]


def spec_example_small(number):
    match number:
        case 1:
            return "one"
        case 2:
            return "a couple"
        case 3:
            return "a few"
        case _:
            return "lots"


def spec_example_large(maximum):
    total = 0
    for i in range(1, maximum + 1):
        for j in range(2, i):
            if i % j == 0:
                continue
        total += i
    return total
