func runShellCheck(s string) error {
	cmd := exec.Command("shellcheck", "-s", "bash", "-", "-e",
		"SC2034", // PREFIX appears unused. Verify it or export it.
	)
	cmd.Stderr = os.Stderr
	cmd.Stdout = os.Stdout

	stdin, err := cmd.StdinPipe()
	if err != nil {
		return err
	}
	go func() {
		_, err := stdin.Write([]byte(s))
		CheckErr(err)

		stdin.Close()
	}()

	return cmd.Run()
}
