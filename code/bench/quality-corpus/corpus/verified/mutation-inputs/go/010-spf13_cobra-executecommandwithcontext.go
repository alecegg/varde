func executeCommandWithContext(ctx context.Context, root *Command, args ...string) (output string, err error) {
	buf := new(bytes.Buffer)
	root.SetOut(buf)
	root.SetErr(buf)
	root.SetArgs(args)

	err = root.ExecuteContext(ctx)

	return buf.String(), err
}
