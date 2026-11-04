public void run() throws Exception {
  Request request = new Request.Builder()
      .url("https://api.github.com/repos/lysine-dev/okhttp/issues")
      .header("User-Agent", "OkHttp Headers.java")
      .addHeader("Accept", "application/json; q=0.5")
      .addHeader("Accept", "application/vnd.github.v3+json")
      .build();

  try (Response response = client.newCall(request).execute()) {
    if (!response.isSuccessful()) throw new IOException("Unexpected code " + response);

    System.out.println("Server: " + response.header("Server"));
    System.out.println("Date: " + response.header("Date"));
    System.out.println("Vary: " + response.headers("Vary"));
  }
}
