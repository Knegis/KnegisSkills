# Intake - settle the brief before you build

**You cannot design your way out of not knowing what the slide says.** Nearly every thin slide traces back to
thin input: the agent didn't know the message, didn't know how much evidence existed, guessed a density level,
and produced a title with three bullets under it because that is all the brief actually contained.

So: **before authoring HTML, settle the five items below. If any is genuinely unclear and the answer would
change the slide, ask. Asking costs one message. Building the wrong slide costs a round trip and erodes trust.**

This is not permission-seeking. Do not ask whether to start, whether the plan is good, or whether to proceed.
Ask only about things you cannot determine yourself and that change the output.

---

## The five

**1. The message.** One declarative sentence per slide - what the reader should believe afterwards. This becomes
the title. If you cannot write it, you do not have a slide yet, you have a topic.

**2. Audience and use.** Investor / client / internal; read cold or presented; part of a pack or standalone.
This sets tone, how much can be assumed, and whether sources are mandatory (`house_style.md` section 6).

**3. Density tier.** T1 statement / T2 standard / T3 dense - see `depth_rubric.md`. Get this wrong and everything
downstream is wrong. **Default: match the pack it sits in.** If the deliverable sits alongside or responds to an
external pack (a due-diligence report, an information memorandum, bank material), that pack sets the bar - read
it before designing, do not guess.

**4. The evidence.** What is the actual source for every number, quote and claim? Named file, tab, page. What is
verified versus what is someone's recollection? **A slide is exactly as deep as its evidence** - if there is one
data point, no format will make it a dense slide, and you should say so rather than padding.

**5. The constraints.** What is off-limits or sensitive - internal-only material, unnamed clients, figures not yet
cleared, a lineage of files you must not overwrite. Ask explicitly when reusing internal material for an external
audience; that judgment is not yours to make silently.

## Ask, or assume and flag?

| Situation | Do this |
|---|---|
| Answer changes the slide's structure or content, and you cannot determine it | **Ask.** Batch your questions into one message. |
| You would have to invent a number, date, client, sequence or result | **Ask.** Never fabricate. If it must ship, mark `[ILLUSTRATIVE]` on the slide itself. |
| Routine judgment a careful colleague would just make (spacing, which grey, column order) | **Decide it.** Do not ask. |
| Answer is knowable from a file you have access to | **Go read it.** Do not ask. |
| Several readings are plausible but all produce acceptable work | **Pick one, state the assumption, keep building.** |

**How to ask:** in plain prose, in the chat, batched - not one question at a time, and not wrapped in a
structured picker. Two to four sharp questions with your recommended answer attached is ideal. Then keep
building everything that does not depend on the answers.

## Worked example - the pattern that works

> **This slide:** three eras of a consulting group disrupting its own market, for an investor pre-read.
> **Settled:** message and audience; the evidence for eras 2 and 3 is sourced from the commercial due-diligence
> readout the deck sits beside; tier T3 to match that pack.
> **Open, and asked:** (1) Era 1 is more than a decade back - I have no hard figures for that period. Narrative
> only, or do numbers exist somewhere? (2) The internal slide I was given names clients and carries an internal
> critique - which parts, if any, are safe for an investor audience?
> **Meanwhile:** built eras 2 and 3 in full, and the layout for all three.

Both questions were answerable in one line each, both changed the slide materially, and neither blocked the 80%
of the work that did not depend on them. That is the shape to aim for.

## After intake, before PowerPoint

Settling the brief does not license building the whole deck end to end. The output of intake is **HTML mockups
you show the user**, not a .pptx. See `html_pipeline.md` -> "The build loop": phase 1 is HTML with the user in
the loop, and there is a hard stop before translation.

## Anti-patterns

- Building a slide, then asking "does this look right?" when the missing input was knowable up front.
- Inventing a plausible sequence of events to fill a narrative gap. (Flag the gap. Always.)
- Treating "be comprehensive" as a brief. Ask what the pack is and what tier it sits at.
- Asking four questions and then stopping. Ask, then continue with everything unaffected.
- Asking permission to begin.
- Settling the brief and then building all the way through to a finished .pptx in one go.
