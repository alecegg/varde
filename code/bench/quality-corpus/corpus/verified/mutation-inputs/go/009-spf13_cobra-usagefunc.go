func (c *Command) UsageFunc() (f func(*Command) error) {
	if c.usageFunc != nil {
		return c.usageFunc
	}
	if c.HasParent() {
		return c.Parent().UsageFunc()
	}
	return func(c *Command) error {
		c.mergePersistentFlags()
		fn := c.getUsageTemplateFunc()
		err := fn(c.OutOrStderr(), c)
		if err != nil {
			c.PrintErrln(err)
		}
		return err
	}
}
