public void run() throws Exception {
  Request request = new Request.Builder()
      .url("http://httpbin.org/delay/1") // This URL is served with a 1 second delay.
      .build();

  // Copy to customize OkHttp for this request.
  OkHttpClient client1 = client.newBuilder()
      .readTimeout(500, TimeUnit.MILLISECONDS)
      .build();
  try (Response response = client1.newCall(request).execute()) {
    System.out.println("Response 1 succeeded: " + response);
  } catch (IOException e) {
    System.out.println("Response 1 failed: " + e);
  }

  // Copy to customize OkHttp for this request.
  OkHttpClient client2 = client.newBuilder()
      .readTimeout(3000, TimeUnit.MILLISECONDS)
      .build();
  try (Response response = client2.newCall(request).execute()) {
    System.out.println("Response 2 succeeded: " + response);
  } catch (IOException e) {
    System.out.println("Response 2 failed: " + e);
  }
}
