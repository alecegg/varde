@Test
public void tagsSeededFromRequest() {
  Request request = new Request.Builder()
    .url(HttpUrl.get("https://square.com/"))
    .tag(Integer.class, 5)
    .tag(String.class, "hello")
    .build();
  Call call = client.newCall(request);

  assertEquals(5, call.tag(Integer.class));
  assertEquals("hello", call.tag(String.class));
  assertEquals(null, call.tag(Boolean.class));
  assertEquals(null, call.tag(Object.class));
}
