public void run() throws Exception {
  Request request = new Request.Builder()
      .url("http://publicobject.com/secrets/hellosecret.txt")
      .build();

  try (Response response = client.newCall(request).execute()) {
    if (!response.isSuccessful()) throw new IOException("Unexpected code " + response);

    System.out.println(response.body().string());
  }
}
