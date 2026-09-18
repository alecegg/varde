# Close

When the user seems satisfied, present the closing confirmation question:

- Visual track: `"Are we aligned on the look, layout, and any interactive behavior, or is there more to refine?"`
- Logic track: `"Does this model handle the cases you're worried about, or is there another scenario to try?"`

Wait for an explicit affirmative answer before ending the session.

On yes: record the final file path and key decisions in the session output. For
the Logic track, name the validated module that should move into production code
— the page shell is disposable.

On no: return to the Propose, Show, Ask, Revise loop.
