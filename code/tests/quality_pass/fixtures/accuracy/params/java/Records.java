public record Point(int x, int y) {
    public Point {
        if (x < 0 || y < 0) {
            throw new IllegalArgumentException("negative");
        }
    }

    public int sum() {
        return x + y;
    }

    public static Point origin() {
        return new Point(0, 0);
    }

    public Point shift(int dx, int dy) {
        return new Point(x + dx, y + dy);
    }
}

record Pair(int left, int right) {
    public Pair(int value) {
        this(value, value);
    }

    public int total() {
        return left + right;
    }
}
