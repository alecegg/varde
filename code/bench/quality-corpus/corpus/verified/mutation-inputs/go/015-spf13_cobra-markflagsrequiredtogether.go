func (c *Command) MarkFlagsRequiredTogether(flagNames ...string) {
	c.mergePersistentFlags()
	for _, v := range flagNames {
		f := c.Flags().Lookup(v)
		if f == nil {
			panic(fmt.Sprintf("Failed to find flag %q and mark it as being required in a flag group", v))
		}
		if err := c.Flags().SetAnnotation(v, requiredAsGroupAnnotation, append(f.Annotations[requiredAsGroupAnnotation], strings.Join(flagNames, " "))); err != nil {
			// Only errs if the flag isn't found.
			panic(err)
		}
	}
}
