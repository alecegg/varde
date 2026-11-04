@Test
public void tagsCanBeComputed() {
  Request request = new Request.Builder()
    .url(HttpUrl.get("https://square.com/"))
    .build();
  Call call = client.newCall(request);

  assertEquals("a", call.tag(String.class, () -> "a"));
  assertEquals("a", call.tag(String.class, () -> "b"));
}
