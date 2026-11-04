"""Historical witness lookups through FrictionRepository."""


def record_historical_occurrence(repository, request):
    from .write import record_historical_occurrence as record

    return record(repository, request)


def find_historical_witness(repository, harness, thread_id, witness_id):
    return repository.find_historical_witness(
        harness=harness, thread_id=thread_id, witness_id=witness_id
    )


def find_historical_fallback_witness(
    repository, harness, thread_id, record_index, record_digest
):
    return repository.find_historical_fallback_witness(
        harness=harness,
        thread_id=thread_id,
        record_index=record_index,
        record_digest=record_digest,
    )
