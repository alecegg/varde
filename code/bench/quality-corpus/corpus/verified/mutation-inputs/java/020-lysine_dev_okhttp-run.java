public void run() throws Exception {
  HeldCertificate localhostCertificate = new HeldCertificate.Builder()
      .addSubjectAlternativeName("localhost")
      .build();

  HandshakeCertificates serverCertificates = new HandshakeCertificates.Builder()
      .heldCertificate(localhostCertificate)
      .build();
  MockWebServer server = new MockWebServer();
  server.useHttps(serverCertificates.sslSocketFactory(), false);
  server.enqueue(new MockResponse());

  HandshakeCertificates clientCertificates = new HandshakeCertificates.Builder()
      .addTrustedCertificate(localhostCertificate.certificate())
      .build();
  OkHttpClient client = new OkHttpClient.Builder()
      .sslSocketFactory(clientCertificates.sslSocketFactory(), clientCertificates.trustManager())
      .build();

  Call call = client.newCall(new Request.Builder()
      .url(server.url("/"))
      .build());
  Response response = call.execute();
  System.out.println(response.handshake().tlsVersion());
}
