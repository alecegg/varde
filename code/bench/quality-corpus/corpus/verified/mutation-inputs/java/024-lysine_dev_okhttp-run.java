public void run() throws Exception {
  File file = new File("README.md");

  Request request = new Request.Builder()
      .url("https://api.github.com/markdown/raw")
      .post(RequestBody.create(file, MEDIA_TYPE_MARKDOWN))
      .build();

  try (Response response = client.newCall(request).execute()) {
    if (!response.isSuccessful()) throw new IOException("Unexpected code " + response);

    System.out.println(response.body().string());
  }
}
