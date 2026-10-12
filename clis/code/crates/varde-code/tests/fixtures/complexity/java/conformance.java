class JavaConformance {
    int if_else_if_else(int value) {
        if (value == 0) return 0;
        else if (value == 1) return 1;
        else if (value == 2) return 2;
        else return 3;
    }
    int else_if_body_nesting(int value) {
        if (value < 0) return 0;
        else if (value > 0) { if (value > 1) return 1; }
        return 2;
    }
    int else_body_nesting(int value) {
        if (value < 0) return 0;
        else { if (value > 0) return 1; }
        return 2;
    }
    int nested_if_nesting(int value) {
        if (value > 0) { if (value > 1) { if (value > 2) return 3; } }
        return 0;
    }
    int loops(int[] values) {
        for (int value : values) { while (value > 0) return value; }
        return 0;
    }
    int switch_once(int value) {
        switch (value) { case 1: return 1; case 2: return 2; default: return 0; }
    }
    int ternary(boolean outer, boolean inner) { return outer ? (inner ? 1 : 2) : 0; }
    int catch_once() {
        try { throw new IllegalArgumentException(); }
        catch (IllegalArgumentException | IllegalStateException error) { if (error != null) return 1; }
        return 0;
    }
    int try_finally_zero() { try { return 1; } finally { int ignored = 0; } }
    int early_return_zero(int value) { if (value < 0) return 0; return value; }
    boolean logical_run_same(boolean a, boolean b, boolean c) { return a && b && c; }
    boolean logical_run_mixed(boolean a, boolean b, boolean c) { return a && b || c; }
    boolean logical_negated_run(boolean a, boolean b, boolean c) { return !(a && b) && c; }
    boolean logical_run_across_lambda(boolean a, boolean b, boolean c) {
        return a && java.util.stream.Stream.of(b, c).anyMatch(value -> value && b && c);
    }
    int lambda_nesting() {
        java.util.function.IntSupplier supplier = () -> { if (true) return 1; return 0; };
        return supplier.getAsInt();
    }
    int class_in_method(int value) {
        class Local { int nested(int input) { if (input > 0) return input; return 0; } }
        return new Local().nested(value);
    }
    int condition_nesting(boolean a, boolean b) {
        if (a && b) { if (b) return 1; }
        return 0;
    }
    int goto_or_labeled_jump(int value) {
        OUT: for (int i = 0; i < 2; i++) { if (value < 0) continue OUT; }
        return value;
    }
    int multi_level_break(int value) {
        OUT: for (int i = 0; i < 2; i++) { for (int j = 0; j < 2; j++) { if (value < 0) break OUT; } }
        return value;
    }
    int recursion_direct(int n) { if (n > 0) return recursion_direct(n - 1); return 0; }
    int recursion_two_calls(int n) { if (n > 0) { recursion_two_calls(n - 1); recursion_two_calls(n - 2); } return 0; }
    int recursion_qualified_self(int n) { if (n > 0) return this.recursion_qualified_self(n - 1); return 0; }
    int recursion_other_receiver(int n, JavaConformance other) { if (n > 0) return other.recursion_other_receiver(n - 1, other); return 0; }
    int recursion_overload_delegate(int n) { return recursion_overload_delegate(n, 0); }
    int recursion_overload_delegate(int n, int ignored) { return ignored; }
    int recursion_in_closure(int n) {
        java.util.function.IntSupplier supplier = () -> { if (n > 0) return recursion_in_closure(n - 1); return 0; };
        return supplier.getAsInt();
    }
    int recursion_same_file_cycle_a(int n) { if (n > 0) return recursion_same_file_cycle_b(n - 1); return 0; }
    int recursion_same_file_cycle_b(int n) { if (n > 0) return recursion_same_file_cycle_a(n - 1); return 0; }
    // absentPeerInAnotherFile is defined in another file, omitted from this fixture.
    int recursion_cross_file_zero(int n) { return absentPeerInAnotherFile(n); }
    int spec_example_small_switch(int number) {
        switch (number) { case 1: return 1; case 2: return 2; case 3: return 3; default: return 4; }
    }
    int spec_example_small_sum(int max) {
        int total = 0;
        OUT: for (int i = 1; i <= max; ++i) {
            for (int j = 2; j < i; ++j) { if (i % j == 0) continue OUT; }
            total += i;
        }
        return total;
    }
    int spec_example_small_catch() {
        try { if (true) { for (int i = 0; i < 10; ++i) { while (false) { } } } }
        catch (RuntimeException error) { if (true) { } }
        return 0;
    }
}

class JavaLargeExamples {
    Object overriddenSymbolFrom(boolean classUnknown, boolean memberMethod, boolean memberStatic,
            boolean canOverride, Boolean overriding, boolean unknownFound) {
        if (classUnknown) return null;
        boolean unknown = false;
        for (Object symbol : new Object[] { new Object() }) {
            if (memberMethod && !memberStatic) {
                if (canOverride) {
                    if (overriding == null) {
                        if (!unknownFound) unknown = true;
                    } else if (overriding) return symbol;
                }
            }
        }
        if (unknown) return null;
        return null;
    }

    void addVersion(Entry entry, Transaction txn, TransactionIndex ti) {
        while (true) {
            try {
                synchronized (this) {
                    if (entry.frst != null) {
                        if (entry.frst.getVersion() > entry.getVersion()) throw new RollbackException();
                        if (txn.isActive()) {
                            for (Entry e = entry.frst; e != null; e = e.getPrevious()) {
                                long version = e.getVersion();
                                long depends = ti.wwDependency(version, txn.getTransactionStatus(), 0);
                                if (depends == TimedOut.VALUE) throw new RetryException(version);
                                if (depends != 0 && depends != Aborted.VALUE) throw new RollbackException();
                            }
                        }
                    }
                    entry.setPrevious(entry.frst);
                    entry.frst = entry;
                    break;
                }
            } catch (RetryException re) {
                try {
                    long depends = ti.wwDependency(re.getVersionHandle(), txn.getTransactionStatus(), DefaultResource.MAX_WAIT_TIME);
                    if (depends != 0 && depends != Aborted.VALUE) throw new RollbackException();
                } catch (InterruptedException ie) { throw new PersistitInterruptedException(ie); }
            } catch (InterruptedException ie) { throw new PersistitInterruptedException(ie); }
        }
    }

    String toRegexp(String antPattern, String directorySeparator) {
        String escapedDirectorySeparator = "\\" + directorySeparator;
        StringBuilder sb = new StringBuilder(antPattern.length());
        sb.append('^');
        int i = antPattern.startsWith("/") || antPattern.startsWith("\\") ? 1 : 0;
        while (i < antPattern.length()) {
            char ch = antPattern.charAt(i);
            if (SPECIAL_CHARS.indexOf(ch) != -1) {
                sb.append('\\').append(ch);
            } else if (ch == '*') {
                if (i + 1 < antPattern.length() && antPattern.charAt(i + 1) == '*') {
                    if (i + 2 < antPattern.length() && isSlash(antPattern.charAt(i + 2))) {
                        sb.append("(?:.*").append(escapedDirectorySeparator).append("|)");
                        i += 2;
                    } else {
                        sb.append(".*");
                        i += 1;
                    }
                } else {
                    sb.append("[^").append(escapedDirectorySeparator).append("]*?");
                }
            } else if (ch == '?') {
                sb.append("[^").append(escapedDirectorySeparator).append("]");
            } else if (isSlash(ch)) {
                sb.append(escapedDirectorySeparator);
            } else {
                sb.append(ch);
            }
            i++;
        }
        sb.append('$');
        return sb.toString();
    }
}
class JavaCallableForms {
    int anonymous_callable() {
        Runnable task = new Runnable() {
            public void run() { if (true) { } }
        };
        task.run();
        return 0;
    }
    int switch_forms(int value) {
        int result = switch (value) { case 1 -> 2; default -> 0; };
        switch (value) { case 1: result++; break; default: result--; }
        return result;
    }
    int instanceof_pattern(Object value) {
        if (value instanceof String text && !text.isBlank()) return text.length();
        return 0;
    }
    int try_with_resources() throws java.io.IOException {
        try (java.io.StringReader resource = new java.io.StringReader("")) {
            if (resource != null) return 1;
        } catch (java.io.IOException error) { return 2; }
        return 0;
    }
}
record JavaRecord(int value) {
    JavaRecord { if (value < 0) throw new IllegalArgumentException(); }
    int read() { if (value > 0) return value; return 0; }
}
