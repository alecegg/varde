#if !VARDE_CSHARP_CONFORMANCE
#define VARDE_CSHARP_CONFORMANCE
using System;
using System.Collections.Generic;
using System.Linq;

class AuditFixture
{
    int if_else_if_else(int value)
    {
        if (value == 0) return 0;
        else if (value == 1) return 1;
        else if (value == 2) return 2;
        else return 3;
    }

    int switch_once(int value)
    {
        switch (value)
        {
            case 1: return 1;
            case 2: return 2;
            default: return 0;
        }
    }

    int SwitchExpression(int value) => value switch { 1 => 1, 2 => 2, _ => 0 };

    bool logical_run_mixed(object value) => value is int and > 0 and < 10 or string;

    int SwitchWhen(object value) => value switch
    {
        int number when number > 0 && number < 10 => number,
        _ => 0,
    };

    int ternary(bool outer, bool inner) => outer ? (inner ? 1 : 2) : 0;

    string null_coalescing_zero(string value) => value?.Trim() ?? "";

    int comprehension_or_query(int[] values) => (from value in values where value > 0 && value < 10 select value).Count();

    bool logical_run_across_lambda(bool a, int[] values) => a && values.Any(value => value > 0 && value < 10);

    int named_nested_function(int value)
    {
        int Inner(int input) { if (input > 0) return input; return 0; }
        return Inner(value);
    }

    int loops(int[] values)
    {
        foreach (var value in values) { if (value > 0) return value; }
        return 0;
    }

    int goto_or_labeled_jump(int value)
    {
        if (value < 0) goto done;
        return value;
    done:
        return 0;
    }

    int catch_once()
    {
        try { throw new InvalidOperationException(); }
        catch (InvalidOperationException error) when (error.Message.Length > 0 && error.Message != "x")
        {
            if (error.Message.Length > 1) return 1;
        }
        finally { }
        return 0;
    }

    int AuditProperty
    {
        get { if (DateTime.Now.Ticks > 0) return 1; return 0; }
        set { if (value > 0) _property = value; }
    }
    private int _property;

    int ExpressionProperty => DateTime.Now.Ticks > 0 ? 1 : 0;

    AuditFixture() { if (_property > 0) _property = 0; }

    static AuditFixture operator +(AuditFixture left, AuditFixture right)
    {
        if (left != null) return left;
        return right;
    }

    static implicit operator int(AuditFixture value)
    {
        if (value != null) return 1;
        return 0;
    }

    class Nested
    {
        public int Read(int value) { if (value > 0) return value; return 0; }
    }
}

class DestructorFixture
{
    ~DestructorFixture() { if (DateTime.Now.Ticks < 0) GC.Collect(); }
}

class SpecExamples
{
    int GetWords(int number)
    {
        switch (number)
        {
            case 1: return 1;
            case 2: return 2;
            case 3: return 3;
            default: return 4;
        }
    }

    int SumOfPrimes(int max)
    {
        int total = 0;
        OUT: for (int i = 1; i <= max; ++i)
        {
            for (int j = 2; j < i; ++j)
            {
                if (i % j == 0) goto NextPrime;
            }
            total += i;
        NextPrime:;
        }
        return total;
    }

    int MyMethod()
    {
        try
        {
            if (true)
            {
                for (int i = 0; i < 10; ++i)
                {
                    while (false) { }
                }
            }
        }
        catch (Exception) { if (true) { } }
        return 0;
    }

    int lambda_nesting()
    {
        Func<int> getValue = () => { if (true) return 1; return 0; };
        return getValue();
    }
}

class DebugSpecExample
{
    int preproc_conditional()
    {
#if DEBUG
        Func<int> getValue = () => { if (true) return 1; return 0; };
#endif
        return getValue();
    }
}

class LargeSpecExamples
{
    int OverriddenSymbolFrom(bool classUnknown, bool memberMethod, bool memberStatic, bool canOverride, bool? overriding, bool unknownFound)
    {
        if (classUnknown) return 0;
        bool unknown = false;
        foreach (var symbol in new[] { 1 })
        {
            if (memberMethod && !memberStatic)
            {
                if (canOverride)
                {
                    if (overriding == null)
                    {
                        if (!unknownFound) unknown = true;
                    }
                    else if (overriding == true) return symbol;
                }
            }
        }
        if (unknown) return 0;
        return -1;
    }

    void AddVersion(Entry entry, Transaction transaction, Func<long, long, long> index)
    {
        while (true)
        {
            try
            {
                lock (this)
                {
                    if (entry.Previous != null)
                    {
                        if (entry.Previous.Version > entry.Version) throw new InvalidOperationException();
                        if (transaction.IsActive)
                        {
                            for (Entry current = entry.Previous; current != null; current = current.Previous)
                            {
                                long version = current.Version;
                                long depends = index(version, transaction.Status);
                                if (depends == -1) throw new TimeoutException();
                                if (depends != 0 && depends != -2) throw new InvalidOperationException();
                            }
                        }
                    }
                    entry.Previous = entry;
                    break;
                }
            }
            catch (RetryException retry)
            {
                try
                {
                    long depends = index(retry.Version, transaction.Status);
                    if (depends != 0 && depends != -2) throw new InvalidOperationException();
                }
                catch (ThreadInterruptedException interrupted)
                {
                    throw new InvalidOperationException(interrupted.Message);
                }
            }
            catch (ThreadInterruptedException interrupted)
            {
                throw new InvalidOperationException(interrupted.Message);
            }
        }
    }

    string ToRegexp(string pattern, bool special, bool doubleStar, bool hasSlash)
    {
        string escapedDirectorySeparator = "\\";
        var result = new System.Text.StringBuilder(pattern.Length);
        int index = pattern.StartsWith("/") || pattern.StartsWith("\\") ? 1 : 0;
        while (index < pattern.Length)
        {
            char current = pattern[index];
            if (special) { }
            else if (current == '*')
            {
                if (index + 1 < pattern.Length && pattern[index + 1] == '*')
                {
                    if (index + 2 < pattern.Length && pattern[index + 2] == '/') { index += 2; }
                    else { index++; }
                }
                else { index++; }
            }
            else if (current == '?') { }
            else if (current == '/') { }
            else { }
            index++;
        }
        return result.ToString();
    }

}

class Entry { public long Version; public Entry Previous; }
class Transaction { public bool IsActive; public long Status; }
class RetryException : Exception { public long Version; }

class MatrixCases
{
    int else_if_body_nesting(int value)
    {
        if (value > 0) return 1;
        else if (value < 0)
        {
            if (value == -1) return 2;
        }
        return 0;
    }

    int else_body_nesting(int value)
    {
        if (value > 0) return 1;
        else
        {
            if (value < 0) return 2;
        }
        return 0;
    }

    int nested_if_nesting(int value)
    {
        if (value > 0)
        {
            if (value < 10) return value;
        }
        return 0;
    }

    void try_finally_zero()
    {
        try { }
        finally { }
    }

    int early_return_zero(bool condition)
    {
        if (condition) return 1;
        return 0;
    }

    bool logical_run_same(object value) => value is int and > 0 and < 10;

    bool pattern_not_zero(object value) => value is not null;

    bool logical_negated_run(bool a, bool b, bool c) => a && !(b && c);

    int condition_nesting(bool condition, bool left, bool right)
    {
        if (condition ? left : right) return 1;
        return 0;
    }

    int goto_case_default(int value)
    {
        switch (value)
        {
            case 0: goto case 1;
            case 1: return 1;
            case 2: goto default;
            default: return 0;
        }
    }

    int multi_level_break(int[][] rows)
    {
        foreach (var row in rows)
        {
            foreach (var value in row)
            {
                if (value > 0) goto done;
            }
        }
    done:
        return 0;
    }

    string null_coalescing_assignment_zero(string value)
    {
        value ??= "";
        return value;
    }
}

class RecursionMatrix
{
    int recursion_direct(int value) => recursion_direct(value - 1);

    int recursion_two_calls(int value) => recursion_two_calls(value - 1) + recursion_two_calls(value - 2);

    int recursion_qualified_self(int value) => this.recursion_qualified_self(value - 1);

    int recursion_other_receiver(RecursionMatrix other, int value) => other.recursion_other_receiver(other, value - 1);

    int recursion_overload_delegate(int value) => recursion_overload_delegate(value, 0);
    int recursion_overload_delegate(int value, int seed) => seed;

    int recursion_in_closure(int value)
    {
        Func<int, int> recurse = next => recursion_in_closure(next - 1);
        return recurse(value);
    }

    int recursion_same_file_cycle_a(int value) => recursion_same_file_cycle_b(value);
    int recursion_same_file_cycle_b(int value) => recursion_same_file_cycle_a(value);

    // CrossFileB is defined in OtherFile.cs, which is intentionally absent from this fixture.
    int recursion_cross_file_zero(int n) => OtherFile.CrossFileB(n - 1);

    int include_guard_zero() => 0;
}

#endif
