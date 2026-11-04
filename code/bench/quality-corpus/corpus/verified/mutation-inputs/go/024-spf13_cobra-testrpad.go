func TestRpad(t *testing.T) {
	tests := []struct {
		name        string
		inputString string
		padding     int
		expected    string
	}{
		{
			name:        "Padding required",
			inputString: "Hello",
			padding:     10,
			expected:    "Hello     ",
		},
		{
			name:        "No padding required",
			inputString: "World",
			padding:     5,
			expected:    "World",
		},
		{
			name:        "Empty string",
			inputString: "",
			padding:     8,
			expected:    "        ",
		},
		{
			name:        "Zero padding",
			inputString: "cobra",
			padding:     0,
			expected:    "cobra",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Act
			got := rpad(tt.inputString, tt.padding)

			// Assert
			if got != tt.expected {
				t.Errorf("Expected rpad: %v\nGot: %v", tt.expected, got)
			}
		})
	}
}
