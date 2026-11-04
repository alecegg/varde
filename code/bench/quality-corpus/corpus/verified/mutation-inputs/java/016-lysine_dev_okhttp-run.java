public void run() throws Exception {
  Request request = new Request.Builder()
      .url("https://publicobject.com/helloworld.txt")
      .build();

  try (Response response = client.newCall(request).execute()) {
    if (!response.isSuccessful()) throw new IOException("Unexpected code " + response);

    System.out.println(response.body().string());
  }
}
