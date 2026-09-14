# Close

When the user seems satisfied, present the closing confirmation question:

- Visual track: `"Are we aligned on the look, layout, and any interactive behavior, or is there more to refine?"`
- Logic track: `"Does this model handle the cases you're worried about, or is there another scenario to try?"`

Wait for an explicit affirmative answer before ending the session.

On affirmative: record the final file path (the winning `v<N>.html`, or `logic.html`) and any key decisions in the session output — do not write to the Decisions Store or modify plan files, that is `/varde-plan`'s responsibility. For the Logic track, call out the validated module (reducer/machine/function set) as the part that should lift into the real codebase, distinct from the throwaway page shell around it.

On negative: return to the Propose, Show, Ask, Revise loop (`references/VISUAL-TRACK.md` or `references/LOGIC-TRACK.md`).
