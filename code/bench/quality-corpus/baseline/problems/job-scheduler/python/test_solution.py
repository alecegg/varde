import unittest

from solution import Job, run_jobs


def plan(jobs, limit):
    return [(r.id, r.start, r.end) for r in run_jobs(jobs, limit)]


class JobSchedulerTest(unittest.TestCase):
    def test_single_job(self):
        self.assertEqual([("a", 0, 3)], plan([Job("a", 3)], 1))

    def test_dependency_order(self):
        jobs = [Job("b", 3, 0, ("a",)), Job("a", 2)]
        self.assertEqual([("a", 0, 2), ("b", 2, 5)], plan(jobs, 2))

    def test_priority_among_ready_jobs(self):
        jobs = [Job("a", 1, 1), Job("b", 1, 5), Job("c", 1, 3)]
        self.assertEqual([("b", 0, 1), ("c", 1, 2), ("a", 2, 3)], plan(jobs, 1))

    def test_limit_one_runs_serially(self):
        jobs = [Job("c", 2), Job("a", 2), Job("b", 2)]
        self.assertEqual([("a", 0, 2), ("b", 2, 4), ("c", 4, 6)], plan(jobs, 1))

    def test_limit_two_runs_in_parallel(self):
        jobs = [Job("a", 2), Job("b", 2), Job("c", 2)]
        self.assertEqual([("a", 0, 2), ("b", 0, 2), ("c", 2, 4)], plan(jobs, 2))

    def test_equal_priority_breaks_by_id(self):
        self.assertEqual(
            [("a", 0, 1), ("x", 1, 2)], plan([Job("x", 1), Job("a", 1)], 1)
        )

    def test_cycle_is_an_error(self):
        with self.assertRaises(ValueError):
            run_jobs([Job("a", 1, 0, ("b",)), Job("b", 1, 0, ("a",))], 2)
        with self.assertRaises(ValueError):
            run_jobs([Job("a", 1, 0, ("a",))], 2)

    def test_invalid_input_is_an_error(self):
        with self.assertRaises(ValueError):
            run_jobs([Job("a", 1, 0, ("missing",))], 1)
        with self.assertRaises(ValueError):
            run_jobs([Job("a", 1)], 0)


if __name__ == "__main__":
    unittest.main()
