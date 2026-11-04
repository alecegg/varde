@Override public Response intercept(Chain chain) throws IOException {
  Request request = chain.request();
  Headers newHeaders = request.headers()
      .newBuilder()
      .add("Date", new Date())
      .build();
  Request newRequest = request.newBuilder()
      .headers(newHeaders)
      .build();
  return chain.proceed(newRequest);
}
