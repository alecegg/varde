"""Published defaults for human validation and generic dataset categories."""

THRESHOLDS = {
    "minimum_units": 40,
    "minimum_category_b_units": 20,
    "minimum_held_out_units": 15,
    "minimum_repeated_units": 10,
    "accuracy": 0.85,
    "wilson_lower_bound": 0.75,
    "bootstrap_lower_bound": 0.75,
    "kappa": 0.65,
    "category_b_accuracy": 0.90,
    "self_consistency": 0.90,
    "bootstrap_seed": 0,
    "bootstrap_replicates": 2000,
}

DEFAULT_CATEGORY_B = "b"
DEFAULT_OVER_SPLIT_CATEGORY = "b"
DEFAULT_HELD_OUT_SPLITS = ("test", "held-out")
DEFAULT_SKIPPED_CHOICES = ("skip", "skipped", "abstain")
DEFAULT_BOOTSTRAP_SEED = int(THRESHOLDS["bootstrap_seed"])
DEFAULT_BOOTSTRAP_REPLICATES = int(THRESHOLDS["bootstrap_replicates"])
