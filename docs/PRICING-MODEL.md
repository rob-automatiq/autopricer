# The retired recommendation engine

The tool used to answer a fourth question: *given a section and a row, what
should I list this at?* That engine was Python, it fitted its surfaces from a
committed snapshot, and it is gone — `git show 246cc8e:autopricer/model.py` has
the implementation.

This is what it did and what it learned, written down so it can be rebuilt as
SQL or as page code without starting from nothing. **Every number below was
fitted on the retired snapshot, which we now know under-counted the season by 22
sales — treat them as the shape of the answer, not as constants to reuse.**

## Three fitted surfaces

All three are medians, so one silly ask cannot move them.

**1. Section quality index.** Within one game, divide each section's median ask
by that game's overall median ask; the index is the median of those ratios
across every game, which divides out game-to-game demand. Centre-court lower
bowl landed at ×2.4–2.9, upper corners ×0.37, courtside ×8–12.

One trap worth keeping: a cell with a single listing has a median equal to its
only ask, so its row ratio is exactly 1.0 — degenerate. The row curve and the
clearing ratio required two listings per cell; the index deliberately accepted
one, because courtside is listed one seat at a time and would otherwise have had
no index at all.

**2. Row curve.** Divide each ask by the median ask of its own (game, section)
cell — that removes both the game and the section and leaves the row. Pool the
ratios by tier and row depth, shrink toward 1.0 by sample size, then fit
monotone non-increasing with pool-adjacent-violators so a row is never worth
less than one behind it, and re-centre on the weighted median. Lower bowl ran
×1.35 at row A to ×0.97 at row Z; the upper bowl was much flatter, ×1.08 to
×1.00, which is the shape you would expect.

**3. Clearing ratio.** Compare every realised sale with the concurrent median
ask in the same game and section. The median was **×0.735** overall — ×0.697
lower bowl, ×0.777 upper.

## Assembling a quote

1. Build a comp set from the live asks in the target section, each re-priced to
   the target row. Under three comps, widen to same-tier sections whose index is
   within 18%, scaling by the ratio of indices, and say so.
2. Blend the comp median against the index model
   (`game level × section index × row factor`) by `n/(n+5)`, so a two-listing
   section leans on the model and a forty-listing section does not.
3. Estimate expected clearing price from comparable realised sales, shrunk
   against `blended ask × clearing ratio`.
4. Take a position on the board: the 10th percentile of comps for aggressive,
   35th for balanced, 65th for patient. Floor the two patient strategies at the
   expected clear; cap all three at the 85th percentile of comps unless the
   clearing price is higher, because a listing priced past the back of the board
   is invisible behind cheaper identical seats.

## What was wrong with it, and would be again

- **The clearing ratio conflated two things.** Listings were a single day's
  board; sales spanned the weeks before it. So ×0.735 mixed the genuine
  ask-to-clear spread with whatever price drift happened over that window. The
  fix is daily listing snapshots over time — the lake keeps historical
  `processed_date` partitions, so it is an extraction job, not new
  instrumentation.
- **It priced off gross only.** Both sale totals are real and mean different
  things (see `DATA-NOTES.md` §4); a rebuilt engine should be explicit about
  which side of the trade it is quoting.
- **It could not see the B2B board.** Consignment inventory was invisible to it,
  which is why a quote once came out at $41 against an $86.74 board. The new
  tool reads that board directly, so a rebuilt engine has no excuse.
- **No time-to-event decay.** Every quote was for the board as it stood that
  day.
- **The comp set was Automatiq's flow, not the market.** Clearing evidence was
  thin in sections our brokers do not hold.

## If rebuilding

The three surfaces are all group-by medians, so they are natural ClickHouse
queries rather than page code — fit them in SQL over all POS event rows for the
game (scoped by `b2bexchangeeventid`), and let the page do only the final
blend. That keeps one code path and gets the surfaces refitted on live data
instead of a snapshot, which is the actual lesson of the first version.
