public void run() throws Exception {
  Request request = new Request.Builder()
      .url("https://publicobject.com/helloworld.txt")
      .build();

  try (Response response = client.newCall(request).execute()) {
    if (!response.isSuccessful()) {
      Headers responseHeaders = response.headers();
      for (int i = 0; i < responseHeaders.size(); i++) {
        System.out.println(responseHeaders.name(i) + ": " + responseHeaders.value(i));
      }

      throw new IOException("Unexpected code " + response);
    }

    System.out.println(response.body().string());
  }
}
