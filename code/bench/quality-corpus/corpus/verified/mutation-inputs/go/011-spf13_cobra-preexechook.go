func preExecHook(c *Command) {
	if MousetrapHelpText != "" && mousetrap.StartedByExplorer() {
		c.Print(MousetrapHelpText)
		if MousetrapDisplayDuration > 0 {
			time.Sleep(MousetrapDisplayDuration)
		} else {
			c.Println("Press return to continue...")
			fmt.Scanln()
		}
		os.Exit(1)
	}
}
