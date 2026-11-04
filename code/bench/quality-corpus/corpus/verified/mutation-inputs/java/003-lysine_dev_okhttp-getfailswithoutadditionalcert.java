@Test public void getFailsWithoutAdditionalCert() throws IOException {
  OkHttpClient client = new OkHttpClient();

  boolean androidMorEarlier = Build.VERSION.SDK_INT <= 23;
  try {
    sendRequest(client, "https://valid-isrgrootx1.letsencrypt.org/robots.txt");
    if (androidMorEarlier) {
      fail();
    }
  } catch (SSLHandshakeException sslhe) {
    assertTrue(androidMorEarlier);
  }
}
