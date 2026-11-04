from varde_runner.job_registry import BUILTIN_JOBS, JobSpec, effective_enabled


def test_builtin_jobs_are_enabled_and_do_not_spend_model_usage():
    assert [job.key for job in BUILTIN_JOBS] == ["sweep", "soak", "review"]
    assert all(effective_enabled(job) for job in BUILTIN_JOBS[:2])
    assert all(not job.spends_model_usage for job in BUILTIN_JOBS[:2])


def test_model_usage_job_defaults_disabled_but_stored_choice_wins():
    job = JobSpec("review", "Review", True, True, "04:00", 0.5)
    assert not effective_enabled(job)
    assert effective_enabled(job, True)
    assert not effective_enabled(job, False)
