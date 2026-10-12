class Receiver { public void name(int value) {} }
class Calls {
    static void alpha(params int[] values) {}
    static void beta(int value) {}
    void Run() {
        alpha(1);
        alpha(2, 3);
        var receiver = new Receiver();
        receiver.name(4);
        beta(5);
    }
}
