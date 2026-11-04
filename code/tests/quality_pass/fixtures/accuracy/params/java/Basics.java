public class Basics {
    private final int x;
    private final String y;

    public Basics(int x, String y) {
        this.x = x;
        this.y = y;
    }

    void zero() {
    }

    void one(int a) {
    }

    int two(int a, int b) {
        return a + b;
    }

    void varargs(int first, String... rest) {
    }

    static void staticZero() {
    }

    @Deprecated
    void annotated(int a) {
    }

    <T> T generic(T value) {
        return value;
    }

    <T, U> void genericPair(T a, U b) {
    }

    void annotatedTwo(@SuppressWarnings("unused") int a, final String b) {
    }
}
