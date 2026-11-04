public record Point(int x, int y) {
    public static final Point ORIGIN = new Point(0, 0);

    public Point {
        if (x < 0 || y < 0) {
            throw new IllegalArgumentException("negative coordinates");
        }
    }

    public Point shift(int delta) {
        return new Point(x + delta, y + delta);
    }

    public int manhattan() {
        return Math.abs(x) + Math.abs(y);
    }
}
