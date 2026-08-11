# Demo script

Five minutes **includes Q&A**, so you have roughly 3½ minutes of talking. The live
dashboard should take 60–75 seconds of that. Rehearse with a stopwatch.

---

## The one-sentence version

> We rank Malaysia's off-grid phone towers by which ones to convert to solar first.

Use this when someone asks in a corridor.

---

## The 30-second version

> A remote tower in Sarawak burns around thirteen thousand litres of diesel a year to
> keep a village online. Converting one to solar costs about forty-two thousand US
> dollars. There are far more of these towers than there is money.
>
> So we built a triage map. It ranks every candidate site by how likely it is to be
> off-grid, how good its sunshine is, how cheaply we can install, and how many people
> depend on it.
>
> It doesn't decide anything. It decides what to look at first.

---

## The live demo — 60 to 75 seconds

Numbers in brackets are what you click. Say the words, don't read them.

**[Land on the Priority map, Malaysia, rural + peri-urban, top 50]**

> Every dot is a candidate tile — about six hundred metres across, not a single tower.
> Amber is low priority, green is high, and the ringed ones are the shortlist. Fifty
> sites, and there's the expected carbon saving across them.

*(The legend under the map says all of this — point at it rather than reciting it, and
move on. If you have a spare beat, the blank middle of the peninsula is worth a
sentence: that's the mountain interior, where nobody runs speed tests.)*

**[Drag the Population slider to 0.5. Pause. Let them watch the map change.]**

> These sliders *are* the scoring, and they're live. Watch what happens if I let
> population drive it.
>
> The list jumps to Kuala Lumpur. Dense, urban, already on the grid — the opposite of
> an off-grid diesel problem. That's why we hold population at zero. Priority comes
> from off-grid likelihood, solar resource, and installation cost.

**[Drag it back to 0. Click any shortlisted site.]**

> And every ranking explains itself. Here's why this site sits where it does — each
> factor, its percentile, its weight, its contribution. No black box.

**[Model tab]**

> We predict internet speed from terrain and population alone, using spatially blocked
> cross-validation. Out-of-block R-squared is 0.60 against 0.75 in-sample. That gap is
> the honest cost of doing it properly — random splits would have flattered us by
> fifteen points.

**[Evidence coverage tab]**

> This is the part we're proudest of. Every gap inside that outline is somewhere we
> *cannot* assess, because remote areas generate almost no speed tests. East Malaysia
> is twelve percent of our data — and it's the region JENDELA Phase 2 actually
> prioritises.
>
> We show that as a finding, not as a blank space.

**[Country dropdown → Indonesia]**

> Same code, different file.

**[Stop. Don't open more tabs.]**

---

## The closing line

> HOMER Pro already designs the microgrid for a single site. Nobody triages a whole
> country. We produce the shortlist worth paying an engineer to model properly.
>
> Every row is a survey trigger, not a verdict.

---

## Q&A — have these ready

**"Your off-grid status is inferred. Why should we trust it?"**
> We don't ask you to. It's a screening flag that triggers a site survey, and operator
> confirmation is step one of our roadmap. What it saves is the cost of surveying
> everything.

**"HOMER Pro already exists."**
> It does, and it's better than us at what it does — bottom-up microgrid design for one
> site. We're the layer above: which sites are worth that engineer's time.

**"Ookla data is crowdsourced and biased."**
> Correct, and that bias runs against us — remote sites generate the fewest tests. We
> apply a minimum-activity rule, we mask thin evidence, and we report our coverage gap
> as a finding rather than hiding it.

**"Why is your top site next to a road?"**
> Because we rank easy-access sites higher — installation and mobilisation cost
> dominate at screening stage. That does bias us away from the hardest terrain in Sabah
> and Sarawak, which is where JENDELA Phase 2 is focused. So this is a first-wave list,
> not a complete one. The hardest sites need a different instrument and that's in the
> roadmap.

**"Are you using the latest data?"** *(or if a teammate mentions the re-export)*
> No, deliberately. We got a re-run this morning that fixed the confidence tiers, and we
> tested it before adopting it. On the identical 2,815 rows — same site IDs, same measured
> speeds — out-of-block R² went from 0.59 to minus 8.7, because the expanded training set
> is 73% tiles with a median of three speed tests. We kept the export that measures
> better. It's written up in the Data integrity tab.

**"What would MCMC do with this on Monday?"**
> Take the top twenty, cross-check against the Phase 2 site pipeline, and order surveys.

**"What's your R²?"**
> 0.60 out-of-block for Malaysia, 0.45 for Indonesia. *(Don't mix these up — the 0.447
> in our notes is the Indonesia figure.)*

---

## Things not to say

- **"Towers."** They're Ookla tiles. Say "candidate sites" or "tiles". Someone will check.
- **"This site is off-grid."** Say "likely off-grid" or "candidate". The contract is on a slide; don't contradict it thirty seconds later.
- **"No coverage here."** Say "no measurement here."
- Don't claim all seven ethics dimensions are green. Three are amber and that's the point.

---

## If the live demo fails

Switch to the screenshots in `fallback/` without commenting on it. Keep talking. Nobody
scores you on your Wi-Fi, but they do notice panic.
