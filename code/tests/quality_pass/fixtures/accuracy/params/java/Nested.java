public class Nested {
    static class Inner {
        void method(int a, int b) {
        }
    }

    void outer(int a) {
        class Local {
            void run(int value) {
            }
        }
        Runnable task = new Runnable() {
            @Override
            public void run() {
            }
        };
        Local local = new Local();
        local.run(a);
        task.run();
    }

    interface Handler {
        void handle(String name, int code);
    }
}
