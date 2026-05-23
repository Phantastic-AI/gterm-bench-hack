# Gemini meta-optimizer proposal

> Proposal artifact only. This is not the live C003 harness unless integrated later.

## Metadata

- Generated at: `2026-05-23T22:17:16Z`
- Model: `gemini-3.5-flash`
- Input: `meta_optimizer/samples/c002_compact_summary.json`
- Gemini API called: `True`
- Live harness modified: `False`

## Proposal

**Title:** Stricter Negative-Context Filtering for Required-Output Extraction

**Boundary:** proposal artifact only; not the actual C003 unless integrated later

**Problem observed:** Required-output extraction is too permissive, occasionally extracting negative-context statements (e.g., failure explanations, placeholders, or echoed instructions) as valid task outputs, leading to false finishes or incorrect reward evaluations.

**Narrow patch:** Introduce a negative-context filter in the harness output extraction utility to reject extracted answers that contain explicit failure indicators, placeholder patterns, or exact prompt-echoed templates.

## Files likely touched if integrated

- harness/utils/extraction.py

## Implementation sketch

- Define a list of negative-context regex patterns (e.g., 'failed to', 'could not find', 'placeholder', 'example output', 'error:') in the extraction module.
- Modify the primary extraction function (e.g., `extract_required_output`) to run candidate matches against these negative patterns.
- If a match is flagged as negative context, discard it or fall back to a secondary extraction strategy rather than returning it as a valid final answer.

## Validation plan

- Unit test the extraction utility with mock agent outputs containing both valid answers and negative-context failure messages.
- Run a dry-run evaluation on a subset of completed C002 tasks to verify that valid outputs are still extracted correctly while false positives are successfully filtered.

## Risks

- Overly aggressive filtering might reject a valid output if it coincidentally contains a blacklisted word (e.g., a task where the correct output literally contains the word 'error').

## Anti-overfit checks

- Ensure the negative patterns are general linguistic indicators of failure/placeholder status rather than task-specific strings.
- Verify that the filter is bypassable or configurable via task metadata if a task explicitly expects a negative-sounding string as its correct answer.

## Expected effect

Reduces false-positive task completions by preventing the harness from accepting agent failure explanations or echoed placeholders as valid task solutions.
