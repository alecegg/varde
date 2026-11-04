func TestActiveHelpAlone(t *testing.T) {
	rootCmd := &Command{
		Use: "root",
		Run: emptyRun,
	}

	activeHelpFunc := func(cmd *Command, args []string, toComplete string) ([]string, ShellCompDirective) {
		comps := AppendActiveHelp(nil, activeHelpMessage)
		return comps, ShellCompDirectiveDefault
	}

	// Test that activeHelp can be added to a root command
	rootCmd.ValidArgsFunction = activeHelpFunc

	output, err := executeCommand(rootCmd, ShellCompNoDescRequestCmd, "")
	if err != nil {
		t.Errorf("Unexpected error: %v", err)
	}

	expected := strings.Join([]string{
		fmt.Sprintf("%s%s", activeHelpMarker, activeHelpMessage),
		":0",
		"Completion ended with directive: ShellCompDirectiveDefault", ""}, "\n")

	if output != expected {
		t.Errorf("expected: %q, got: %q", expected, output)
	}

	rootCmd.ValidArgsFunction = nil

	// Test that activeHelp can be added to a child command
	childCmd := &Command{
		Use:   "thechild",
		Short: "The child command",
		Run:   emptyRun,
	}
	rootCmd.AddCommand(childCmd)

	childCmd.ValidArgsFunction = activeHelpFunc

	output, err = executeCommand(rootCmd, ShellCompNoDescRequestCmd, "thechild", "")
	if err != nil {
		t.Errorf("Unexpected error: %v", err)
	}

	expected = strings.Join([]string{
		fmt.Sprintf("%s%s", activeHelpMarker, activeHelpMessage),
		":0",
		"Completion ended with directive: ShellCompDirectiveDefault", ""}, "\n")

	if output != expected {
		t.Errorf("expected: %q, got: %q", expected, output)
	}
}
