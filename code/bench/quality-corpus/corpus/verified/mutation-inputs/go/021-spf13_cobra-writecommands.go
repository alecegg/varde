func writeCommands(buf io.StringWriter, cmd *Command) {
	WriteStringAndCheck(buf, "    commands=()\n")
	for _, c := range cmd.Commands() {
		if !c.IsAvailableCommand() && c != cmd.helpCommand {
			continue
		}
		WriteStringAndCheck(buf, fmt.Sprintf("    commands+=(%q)\n", c.Name()))
		writeCmdAliases(buf, c)
	}
	WriteStringAndCheck(buf, "\n")
}
