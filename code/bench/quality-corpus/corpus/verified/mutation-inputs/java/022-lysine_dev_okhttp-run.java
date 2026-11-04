public void run() throws Exception {
  Request request = new Request.Builder()
      .url("https://api.github.com/gists/c2a7c39532239ff261be")
      .build();
  try (Response response = client.newCall(request).execute()) {
    if (!response.isSuccessful()) throw new IOException("Unexpected code " + response);

    Gist gist = gistJsonAdapter.fromJson(response.body().source());

    for (Map.Entry<String, GistFile> entry : gist.files.entrySet()) {
      System.out.println(entry.getKey());
      System.out.println(entry.getValue().content);
    }
  }
}
