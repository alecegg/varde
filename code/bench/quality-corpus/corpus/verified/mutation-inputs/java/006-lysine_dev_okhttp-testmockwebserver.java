@Test
public void testMockWebServer() throws IOException {
  MockWebServer server = new MockWebServer();
  server.enqueue(new MockResponse(200, Headers.of(), "Hello, Java9!"));
  server.start();

  // Just check we can run code that depends on OkHttp types
  Call call = OkHttpCaller.callOkHttp(server.url("/"));

  try (Response response = call.execute();) {
    System.out.println(response.body().string());
  }
}
