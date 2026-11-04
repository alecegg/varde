func TestPwshCompletionNoActiveHelp(t *testing.T) {
	c := &Command{Use: "c", Run: emptyRun}

	buf := new(bytes.Buffer)
	assertNoErr(t, c.GenPowerShellCompletion(buf))
	output := buf.String()

	// check that active help is being disabled
	activeHelpVar := activeHelpEnvVar(c.Name())
	check(t, output, fmt.Sprintf("${env:%s}=0", activeHelpVar))
}
