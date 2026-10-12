class Calls {
    static void alpha(int... values) {}
    static void beta(int value) {}
    static class Receiver { void name(int value) {} }
    void run() {
        alpha(1);
        alpha(2, 3);
        Receiver receiver = new Receiver();
        receiver.name(4);
        beta(5);
    }
}
