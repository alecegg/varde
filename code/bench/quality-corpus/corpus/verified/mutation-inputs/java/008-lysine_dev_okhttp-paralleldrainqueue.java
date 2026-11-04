private void parallelDrainQueue(int threadCount) {
  ExecutorService executor = Executors.newFixedThreadPool(threadCount);
  for (int i = 0; i < threadCount; i++) {
    executor.execute(() -> {
      try {
        drainQueue();
      } catch (Throwable e) {
        e.printStackTrace();
      }
    });
  }
  executor.shutdown();
}
