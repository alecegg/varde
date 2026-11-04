// Copyright 2017 Manu Martinez-Almeida.  All rights reserved.
// Use of this source code is governed by a MIT style
// license that can be found in the LICENSE file.

func TestUnixSocket(t *testing.T) {
	router := New()

	go func() {
		router.GET("/example", func(c *Context) { c.String(http.StatusOK, "it worked") })
		assert.NoError(t, router.RunUnix("/tmp/unix_unit_test"))
	}()
	// have to wait for the goroutine to start and run the server
	// otherwise the main thread will complete
	time.Sleep(5 * time.Millisecond)

	c, err := net.Dial("unix", "/tmp/unix_unit_test")
	assert.NoError(t, err)

	fmt.Fprint(c, "GET /example HTTP/1.0\r\n\r\n")
	scanner := bufio.NewScanner(c)
	var response string
	for scanner.Scan() {
		response += scanner.Text()
	}
	assert.Contains(t, response, "HTTP/1.0 200", "should get a 200")
	assert.Contains(t, response, "it worked", "resp body should match")
}