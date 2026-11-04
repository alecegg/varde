"""Plain data shapes used by the calibration store."""

from typing import Literal, NotRequired, TypedDict


class Item(TypedDict):
    id: str
    language: str
    task_id: str
    pair_group_id: str
    text: str
    license: str
    split: str
    content_sha256: NotRequired[str]
    metadata: NotRequired[dict[str, object]]


class Unit(TypedDict):
    id: str
    kind: Literal["pair", "triple", "single"]
    item_ids: list[str]
    pair_group_id: str
    task_id: str
    split: str


class Task(TypedDict):
    id: str
    description: str
    behaviour_test_path: NotRequired[str]
    behaviour_tests: NotRequired[list[dict[str, str]]]


class LabelRecord(TypedDict):
    unit_id: str
    a_item_id: str
    b_item_id: str
    a_sha256: str
    b_sha256: str
    order_shown: list[str]
    choice: Literal["A", "B", "tie"]
    confidence: Literal["high", "medium", "low"]
    session_id: str
    rater_id: str
    rater_kind: Literal["human", "llm-lens", "llm-personal"]
    label_source: str
    timestamp: str
    duration_ms: int
    reason: NotRequired[str]
    tags: NotRequired[list[str]]


class Session(TypedDict):
    id: str
    rater_id: str
    started_at: str
    ended_at: NotRequired[str]
    tool_version: str
    seed: int
    randomization_summary: NotRequired[dict[str, object]]
    breaks: NotRequired[list[dict[str, object]]]


class Rater(TypedDict):
    id: str
    kind: Literal["human", "llm-lens", "llm-personal"]
    display_name: NotRequired[str]
    language_familiarity: NotRequired[dict[str, str]]


class ValidationRecord(TypedDict):
    language: str
    state: Literal["report-only", "panel-validated", "human-validated"]
    rater_id: str
    rater_kind: Literal["human", "llm-lens", "llm-personal"]
    n_units: int
    n_non_tie: int
    n_category_b: int
    n_held_out: int
    date: str
    validated_against: dict[str, str]
    thresholds: dict[str, bool]
    agreement_with_panel: dict[str, object]
    panel_version: NotRequired[str]
    rubric_sha256: NotRequired[str]
    transfer: NotRequired[dict[str, object]]
    label_batches: list[str]
    stale: bool


class Run(TypedDict):
    id: str
    model_id: str
    provider_version: NotRequired[str]
    decoding_settings: NotRequired[dict[str, object]]
    seeds: NotRequired[list[int]]
    order_rule: NotRequired[str]
    prompt_sha256: str
    raw_response: NotRequired[str]
    parse_status: str


class LabelBatch(TypedDict):
    id: str
    sha256: str
    previous_chain_sha256: str
    chain_sha256: str


class Manifest(TypedDict):
    schema_version: int
    dataset_id: str
    item_hashes: dict[str, str]
    splits: dict[str, str]
    label_batches: list[LabelBatch]
    chain_sha256: str
