# Open Questions for the Strategy Author

These are the spots where the spec is silent or ambiguous. **Only the strategy author can answer these** — they change how the bot behaves with real money, so we do not guess. Until answered, the code uses the documented "default" and is marked with a `# OPEN-Q#` comment so it is easy to find and change later.

Julian: copy this list to the strategy author and bring back answers.

> **Status (2026-05-26, updated after reading the ORIGINAL source PDF):**
> The original source document (`STRATEGY_SPEC_ORIGINAL.md`) **settles Q1 and Q3 directly** — and on **Q1 it overrides the earlier proxy guess** (the original says Alarm D uses the **session** peak, not per-Strike). Q3 is confirmed (`>=`). The remaining five (2, 4, 5, 6, 7) are genuinely not addressed in the original, so the proxy defaults stand and only Q1's new sub-question + those five need eventual author input.
>
> **Source priority:** ORIGINAL PDF > proxy reasoning > expanded brief.

| # | Question | Why it matters | Default in code | Resolution |
|---|----------|----------------|-----------------|------------|
| 1 | **Alarm D scope** — does "HVP / High Water Mark" mean peak 5m ADX for the *whole session*, or just the *current Strike* (`Trade_HVP`)? | Decides when the bot bails on a fading trend. | **SESSION peak (HWM)** — *changed from per-Strike* | ✅ **ANSWERED BY ORIGINAL.** Alarm D literally reads "5m ADX < 75% **session peak (HWM)**," and the glossary defines HWM as "peak session indicator." So Alarm D = **session-wide** peak. The earlier proxy guess (per-Strike) was **wrong** — overridden. **NEW sub-question for author:** the original also defines `Trade_HVP` (per-Strike peak) but **never uses it** in any alarm. Is that intentional/vestigial, or did you mean Alarm D to use `Trade_HVP`? Default until told otherwise: session HWM, `Trade_HVP` tracked but unused. |
| 2 | **Ratchet vs hard stop** — when Alarm C or E tightens the stop, does the new stop *replace* the original $500 stop, or do both coexist? | Two live stops could double-exit. | Replace with the tighter (more protective) | 🟡 Not explicit in original, but original says "**ratchet** STOP MARKET" (singular, moved — not a 2nd order), consistent with our default. Confirm with author. |
| 3 | **Volume gate** — exactly-equal (`>=`) or strictly exceed (`>`)? | Edge case on borderline breakouts. | `>=` (equal allowed) | ✅ **ANSWERED BY ORIGINAL** — written literally as `>= 100% of 55-bar rolling average`. |
| 4 | **Scale-in stop** — when the 2nd 50% fills, does the $500 hard stop recalc for the full position? | Affects total risk per trade. | Yes — recalc on blended entry + full size | 🟡 Not addressed in original. Default holds (only way to honor the absolute "-$500 level" rule on the full position). Confirm with author. |
| 5 | **Direction flip** — can Strike 2 go short if Strike 1 was long (same ticker, same day)? | Could double exposure to a choppy stock. | Yes, if conditions trigger | 🟡 Not addressed in original (only "Position = 0 between strikes"). Default holds; **log flips as a distinct event** to evaluate later. Confirm with author. |
| 6 | **Bar timezone** — feed returns UTC, convert to ET internally? | Wrong tz = wrong opening range = broken strategy. | UTC in → convert to America/New_York (DST-aware) | 🟡 Implementation detail, not in original. Note: original labels times "EST" but means market time → use America/New_York (handles EST/EDT). Default holds. |
| 7 | **Halt handling** — what on a LULD halt while in a position? | Spec doesn't cover it; halts common on gappers. | Cancel ALL working orders (incl. hard stop) + pause alarms; on resume re-place stop + resume; no auto-exit | 🟡 Not addressed in original. Default holds. Confirm with author. |

## New questions found during the build

_(Claude adds rows here as ambiguities surface while coding. Each is also tagged `# OPEN-Q#` at the relevant line.)_
