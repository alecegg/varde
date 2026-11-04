public void run() throws Exception {
  Request request = new Request.Builder()
      .url("https://publicobject.com/robots.txt")
      .build();

  try (Response response = client.newCall(request).execute()) {
    if (!response.isSuccessful()) throw new IOException("Unexpected code " + response);

    for (Certificate certificate : response.handshake().peerCertificates()) {
      System.out.println(CertificatePinner.pin(certificate));
    }
  }
}
