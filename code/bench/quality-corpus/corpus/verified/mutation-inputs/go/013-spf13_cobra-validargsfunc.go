func validArgsFunc(cmd *Command, args []string, toComplete string) ([]string, ShellCompDirective) {
	if len(args) != 0 {
		return nil, ShellCompDirectiveNoFileComp
	}

	var completions []string
	for _, comp := range []string{"one\tThe first", "two\tThe second"} {
		if strings.HasPrefix(comp, toComplete) {
			completions = append(completions, comp)
		}
	}
	return completions, ShellCompDirectiveDefault
}
