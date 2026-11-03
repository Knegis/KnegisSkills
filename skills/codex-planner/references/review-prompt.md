# Stage: review

Review the supplied candidate, not a hypothetical corrected version. Trace the
brief's requirements to tasks; check interfaces, dependencies, validation and
failure handling. Check both agents' first-round findings against the decision
log and candidate: were accepted fixes incorporated and rejected findings
supported? Do not accept a resolution merely because Claude asserts it.

Return stage `review`. Use verdict `ready` only if this exact candidate can be
handed to an implementer without material unanswered decisions or blockers.
Otherwise use `needs_changes` or `cannot_assess`. Report material user questions
with status `needs_input`. Give new findings X-R prefixed IDs. No implementation
or additional review rounds; any limitations must remain visible in `text`.
