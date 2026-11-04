// Package fixtures holds hand-labelled parameter-count audit fixtures.
package fixtures

import "strings"

func zero() int { return 0 }

func one(value int) int { return value }

func two(a int, b int) int { return a + b }

func grouped(a, b int, c string) int { return a + b + len(c) }

func unnamed(int, string) {}

func variadic(first int, rest ...string) int { return first + len(rest) }

func onlyVariadic(rest ...int) int { return len(rest) }

func pointers(p *int, q **int) {}

func callback(fn func(int, int) int, value int) int { return fn(value, value) }

func channels(in <-chan int, out chan<- int) {}

func joined(parts []string, separator string, upper bool) string {
	return strings.Join(parts, separator)
}

func four(a, b int, c, d string) int { return a + b + len(c) + len(d) }
