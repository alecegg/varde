func TestBashCompletionHiddenFlag(t *testing.T) {
	c := &Command{Use: "c", Run: emptyRun}

	const flagName = "hiddenFlag"
	c.Flags().Bool(flagName, false, "")
	assertNoErr(t, c.Flags().MarkHidden(flagName))

	buf := new(bytes.Buffer)
	assertNoErr(t, c.GenBashCompletion(buf))
	output := buf.String()

	if strings.Contains(output, flagName) {
		t.Errorf("Expected completion to not include %q flag: Got %v", flagName, output)
	}
}
