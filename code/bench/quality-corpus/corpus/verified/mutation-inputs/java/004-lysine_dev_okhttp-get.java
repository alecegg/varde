@Test public void get() throws IOException {
  OkHttpClient client = new OkHttpClient();
  Request request = new Request.Builder()
      .url("https://google.com/robots.txt")
      .build();
  try (Response response = client.newCall(request).execute()) {
    assertEquals(200, response.code());
    assertEquals(Protocol.HTTP_2, response.protocol());
  }
}
