"""Shared instruction block markers and notes."""

TOZ_BLOCK_START = "<!-- varde-toz:start -->"
TOZ_BLOCK_END = "<!-- varde-toz:end -->"
LEARN_NOTE = (
    "Record friction as it happens with `varde learn friction add`. Record each user "
    "correction with the user's stated reason. Do not record predicted risks."
)
HOW_NOTE = (
    "Skills are slim: their steps, methods and examples live in how topics. "
    "List a skill's topics with `varde learn how <skill>` and read one with "
    "`varde learn how <skill> <step>`."
)
TOZ_NOTE = (
    "varde-toz (tool-output-zone) is active. Large supported tool results are "
    "captured by handle. "
    "For batched or noisy commands, use native code mode on Pi or on Codex with "
    "`code_mode` enabled, "
    "otherwise `varde run run` (the varde-toz skill covers other code modes), and "
    "print a filtered summary. "
    "Recover details with `varde run query --handle <H>` instead of rerunning; "
    "read the varde-toz skill when a handle appears."
)


def toz_instruction_block(template: str) -> str:
    start = template.find(TOZ_BLOCK_START)
    if start < 0:
        raise ValueError("Toz note block start marker missing")
    start += len(TOZ_BLOCK_START)
    relative_end = template[start:].find(TOZ_BLOCK_END)
    if relative_end < 0:
        raise ValueError("Toz note block end marker missing")
    block = template[start : start + relative_end].strip("\n")
    return block.replace("{{TOZ_SHARED_NOTE}}", TOZ_NOTE)
