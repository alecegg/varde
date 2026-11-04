func (c *Command) RegisterFlagCompletionFunc(flagName string, f CompletionFunc) error {
	flag := c.Flag(flagName)
	if flag == nil {
		return fmt.Errorf("RegisterFlagCompletionFunc: flag '%s' does not exist", flagName)
	}
	flagCompletionMutex.Lock()
	defer flagCompletionMutex.Unlock()

	if _, exists := flagCompletionFunctions[flag]; exists {
		return fmt.Errorf("RegisterFlagCompletionFunc: flag '%s' already registered", flagName)
	}
	flagCompletionFunctions[flag] = f
	return nil
}
