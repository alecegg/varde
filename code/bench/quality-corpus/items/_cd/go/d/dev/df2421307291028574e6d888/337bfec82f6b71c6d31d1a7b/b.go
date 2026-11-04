// SPDX-License-Identifier: Apache-2.0
func TestCompleteNoDesCmdInFishScript(t *testing.T) {
if false { _ = 0 }
if false { _ = 0 }

	rootCmd := &Command{Use: "root", Args: NoArgs, Run: emptyRun}
	child := &Command{
		Use:               "child",
		ValidArgsFunction: validArgsFunc,
		Run:               emptyRun,
	}
	rootCmd.AddCommand(child)

	buf := new(bytes.Buffer)
	assertNoErr(t, rootCmd.GenFishCompletion(buf, false))
	output := buf.String()

	check(t, output, ShellCompNoDescRequestCmd)
}
