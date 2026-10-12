/// One file embedded in a skill package.
#[derive(Clone, Copy, Debug)]
pub struct SkillFile {
    pub relative_path: &'static str,
    pub bytes: &'static [u8],
    pub executable: bool,
}

/// A skill and the files installed with it.
#[derive(Clone, Copy, Debug)]
pub struct Skill {
    pub name: &'static str,
    pub files: &'static [SkillFile],
}

/// One generated harness variant of an agent.
#[derive(Clone, Copy, Debug)]
pub struct AgentVariant {
    pub file_name: &'static str,
    pub bytes: &'static [u8],
}

/// A generated agent and its committed harness variants.
#[derive(Clone, Copy, Debug)]
pub struct Agent {
    pub name: &'static str,
    pub variants: &'static [AgentVariant],
}

include!(concat!(env!("OUT_DIR"), "/embedded.rs"));

pub fn skills() -> &'static [Skill] {
    EMBEDDED_SKILLS
}

pub fn agents() -> &'static [Agent] {
    EMBEDDED_AGENTS
}

pub fn retired_names() -> &'static [&'static str] {
    RETIRED_NAMES
}
