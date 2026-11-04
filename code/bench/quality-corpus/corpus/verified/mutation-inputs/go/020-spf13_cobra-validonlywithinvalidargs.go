func validOnlyWithInvalidArgs(err error, t *testing.T) {
	if err == nil {
		t.Fatal("Expected an error")
	}
	got := err.Error()
	expected := `invalid argument "a" for "c"`
	if got != expected {
		t.Errorf("Expected: %q, got: %q", expected, got)
	}
}
