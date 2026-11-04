public void run() throws Exception {
  Request request = new Request.Builder()
      .url("http://httpbin.org/delay/2") // This URL is served with a 2 second delay.
      .build();

  final long startNanos = System.nanoTime();
  final Call call = client.newCall(request);

  // Schedule a job to cancel the call in 1 second.
  executor.schedule(() -> {
    System.out.printf("%.2f Canceling call.%n", (System.nanoTime() - startNanos) / 1e9f);
    call.cancel();
    System.out.printf("%.2f Canceled call.%n", (System.nanoTime() - startNanos) / 1e9f);
  }, 1, TimeUnit.SECONDS);

  System.out.printf("%.2f Executing call.%n", (System.nanoTime() - startNanos) / 1e9f);
  try (Response response = call.execute()) {
    System.out.printf("%.2f Call was expected to fail, but completed: %s%n",
        (System.nanoTime() - startNanos) / 1e9f, response);
  } catch (IOException e) {
    System.out.printf("%.2f Call failed as expected: %s%n",
        (System.nanoTime() - startNanos) / 1e9f, e);
  }
}
