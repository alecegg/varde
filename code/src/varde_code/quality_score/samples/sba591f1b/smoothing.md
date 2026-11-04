# Style disputes

- **Granularity: inline calculation over `judge-extract`'s many helpers.** The fee method separates the public class/range checks from rate-based arithmetic, while keeping the small tier and block calculations together where their control flow is easiest to follow.
- **Naming length: `judge-names`' clear, moderate names.** Names such as `vehicleClass`, `blockHours`, and `remaining` explain their values without repeating the surrounding domain in every identifier.
- **Commenting: `judge-inline`'s light touch over `judge-defensive`'s line-by-line comments.** The method and variable names make these short steps clear; comments repeating each guard or assignment would add noise.
- **Abstraction level: `judge-inline`'s direct data and methods over `judge-classes`' model and strategy types.** The three fixed rates and one pricing rule do not need separate vehicle objects, interfaces, or a strategy instance.
