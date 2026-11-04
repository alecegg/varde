## Idiomatic patterns

Go favors explicit error checks, short contextual names, table-driven tests, and direct use of goroutines and channels. Repeated checks commonly make failure paths visible.

## Not a defect by itself

An `if err != nil` return, a conventional short name such as `ctx` or `r`, and straightforward concurrency are not defects by themselves. Consider whether the success path remains clear.
