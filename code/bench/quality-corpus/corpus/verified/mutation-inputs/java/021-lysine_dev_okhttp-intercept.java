@Override public Response intercept(Chain chain) throws IOException {
  long t1 = System.nanoTime();
  Request request = chain.request();
  logger.info(String.format("Sending request %s on %s%n%s",
      request.url(), chain.connection(), request.headers()));
  Response response = chain.proceed(request);

  long t2 = System.nanoTime();
  logger.info(String.format("Received response for %s in %.1fms%n%s",
      request.url(), (t2 - t1) / 1e6d, response.headers()));
  return response;
}
