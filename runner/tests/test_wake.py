from varde_runner.wake import wake_agent_id


def test_wake_agent_id_reads_generic_and_legacy_ids():
    assert wake_agent_id({"agent_id": "new", "paseo_id": "old"}) == "new"
    assert wake_agent_id({"paseo_id": "old"}) == "old"
    assert wake_agent_id(None) is None
