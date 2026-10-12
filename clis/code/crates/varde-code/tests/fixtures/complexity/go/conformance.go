package main

func if_else_if_else(value int) int {
	if value > 0 {
		return 1
	} else if value < 0 {
		return -1
	} else {
		return 0
	}
}

func else_if_body_nesting(value int) int {
	if value > 0 {
		return 1
	} else if value < 0 {
		if value < -10 {
			return -2
		}
	}
	return 0
}

func else_body_nesting(value int) int {
	if value > 0 {
		return 1
	} else {
		if value < -10 {
			return -2
		}
	}
	return 0
}

func nested_if_nesting(a, b bool) bool {
	if a {
		if b {
			return true
		}
	}
	return false
}

func loops(values []int) int {
	for i := range values {
		for j := 0; j < len(values); j++ {
			if values[j] > 0 {
				break
			}
		}
		_ = i
	}
	i := 0
	for i < len(values) {
		i++
		break
	}
	for {
		break
	}
	return i
}

func switch_once(value any, channel <-chan int) int {
	switch value {
	case 1:
		return 1
	default:
		return 0
	}
	switch value.(type) {
	case int:
		return 2
	default:
		return 0
	}
	select {
	case <-channel:
		return 3
	default:
		return 0
	}
}

func early_return_zero(value int) int {
	if value < 0 {
		return 0
	}
	return value
}

func logical_run_same(a, b, c bool) bool {
	return a && b && c
}

func logical_run_mixed(a, b, c bool) bool {
	return a && b || c
}

func logical_negated_run(a, b, c bool) bool {
	if a && !(b && c) {
		return true
	}
	return false
}

func logical_run_across_lambda(a, b, c bool) bool {
	return a && func() bool { return b && c }()
}

func lambda_nesting(flag bool) bool {
	return func() bool {
		if flag {
			return true
		}
		return false
	}()
}

func condition_nesting(flag bool) int {
	if func() bool {
		if flag {
			return true
		}
		return false
	}() {
		return 1
	}
	return 0
}

func goto_or_labeled_jump(value int) int {
	if value < 0 {
		goto done
	}
done:
	return value
}

func multi_level_break(values []int) int {
outer:
	for i := range values {
		for j := 0; j < len(values); j++ {
			if values[j] == 0 {
				continue outer
			}
			break outer
		}
		_ = i
	}
	return 0
}

func recursion_direct(value int) int {
	if value <= 0 {
		return 0
	}
	return recursion_direct(value - 1)
}

func recursion_two_calls(value int) int {
	return recursion_two_calls(value-1) + recursion_two_calls(value-2)
}

type Worker struct{}

func (w *Worker) recursion_qualified_self(value int) int {
	return w.recursion_qualified_self(value - 1)
}

func (w *Worker) recursion_other_receiver(other *Worker, value int) int {
	return other.recursion_other_receiver(other, value-1)
}

func recursion_in_closure(value int) int {
	callback := func() int { return recursion_in_closure(value - 1) }
	return callback()
}

func recursion_same_file_cycle_a(value int) int {
	return recursion_same_file_cycle_b(value)
}

func recursion_same_file_cycle_b(value int) int {
	return recursion_same_file_cycle_a(value)
}

// missingPeer is intentionally absent and represents a peer in another file.
func recursion_cross_file_zero(value int) int {
	return missingPeer(value - 1)
}

func get_words(value int) string {
	switch value {
	case 1:
		return "one"
	case 2:
		return "a couple"
	case 3:
		return "a few"
	default:
		return "lots"
	}
}

func sum_primes(max int) int {
	total := 0
outer:
	for i := 1; i <= max; i++ {
		for j := 2; j < i; j++ {
			if i%j == 0 {
				continue outer
			}
		}
		total += i
	}
	return total
}
