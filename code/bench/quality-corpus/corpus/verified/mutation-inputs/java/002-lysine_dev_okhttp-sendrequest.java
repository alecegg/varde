private void sendRequest(OkHttpClient client, String url) throws IOException {
  Request request = new Request.Builder()
          .url(url)
          .build();
  try (Response response = client.newCall(request).execute()) {
    assertTrue(response.code() == 200 || response.code() == 404);
    assertEquals(Protocol.HTTP_2, response.protocol());

    for (Certificate c: response.handshake().peerCertificates()) {
      X509Certificate x = (X509Certificate) c;
      System.out.println(x.getSubjectDN());
    }
  }
}
