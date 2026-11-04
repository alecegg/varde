func TestActiveHelpForFlag(t *testing.T) {
	rootCmd := &Command{
		Use: "root",
		Run: emptyRun,
	}
	flagname := "flag"
	rootCmd.Flags().String(flagname, "", "A flag")

	// Test that multiple activeHelp message can be added
	_ = rootCmd.RegisterFlagCompletionFunc(flagname, func(cmd *Command, args []string, toComplete string) ([]string, ShellCompDirective) {
		comps := []string{"first"}
		comps = AppendActiveHelp(comps, activeHelpMessage)
		comps = append(comps, "second")
		comps = AppendActiveHelp(comps, activeHelpMessage2)
		return comps, ShellCompDirectiveNoFileComp
	})

	output, err := executeCommand(rootCmd, ShellCompNoDescRequestCmd, "--flag", "")
	if err != nil {
		t.Errorf("Unexpected error: %v", err)
	}

	expected := strings.Join([]string{
		"first",
		fmt.Sprintf("%s%s", activeHelpMarker, activeHelpMessage),
		"second",
		fmt.Sprintf("%s%s", activeHelpMarker, activeHelpMessage2),
		":4",
		"Completion ended with directive: ShellCompDirectiveNoFileComp", ""}, "\n")

	if output != expected {
		t.Errorf("expected: %q, got: %q", expected, output)
	}
}
