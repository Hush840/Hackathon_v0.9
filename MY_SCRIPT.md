# Member 3 — dashboard demo + Q&A defence

Your slot: **~2 minutes**. Roughly 75 seconds of driving, then you own the technical
questions. Live on `hackathonmcmc.streamlit.app`.

---

## The framework

Four beats, in this order, no exceptions:

1. **Orient** — what a dot is, before anyone wonders
2. **Prove it's live** — move a slider, let the map answer
3. **Prove it's honest** — the gaps, not the shortlist
4. **Prove it scales** — change country, say nothing else

The logic: judges assume a hackathon map is a static picture until you move something.
Once they believe it's live, they'll believe the rest. Once they've seen you volunteer a
weakness, they stop hunting for one.

**Show, then say.** Click first, then talk over what's already changed. Never narrate a
click you haven't made — you'll end up describing a screen the room can't see yet.

**Don't read the KPIs aloud.** They're on screen in 40-point type. Reading them out is
the fastest way to sound like you have nothing else to say.

---

## Before you go up

- App open, Malaysia loaded, **Priority map** tab, sliders at defaults, rings on
- A second tab already on `hackathonmcmc.streamlit.app` in case the first one wedges
- `fig_priority.png` and `fig_coverage.png` open in an image viewer, minimised
- Browser zoom at 80% so the whole map and the KPI row fit without scrolling
- Wifi checked. If it's bad, run localhost instead and say nothing about it

---

## The script — 75 seconds

Bracketed lines are what you *do*. Say the rest; don't read it.

**[Land on Priority map, Malaysia]**

> Every dot is a candidate tile, about six hundred metres across — not a tower. Amber is
> low priority, green is high, ringed ones are the shortlist. Fifty sites out of fourteen
> thousand that carried enough evidence to rank.

*Two seconds of silence. Let them look.*

**[Point at the East Malaysia KPI: 0%.]**

> And look at that fourth number. Zero percent of our shortlist is in East Malaysia —
> Sabah and Sarawak — which is the region JENDELA Phase 2 explicitly prioritises. Twelve
> percent of our ranked tiles are there. None of them made the top fifty.

**[Drag Ease of access to 0. Don't talk while dragging. Let the map redraw.]**

> That's the ease-of-access weight. It penalises remote sites because mobilisation costs
> more.

**[Now point at the KPIs.]**

> Take it out and East Malaysia goes from zero to thirty-two percent — and total carbon
> avoided moves by less than half a percent. So that weighting wasn't buying us
> abatement. It was buying us convenience, at the expense of the region the policy is
> actually about.
>
> We left the default where the pipeline put it and reported the consequence, rather than
> tuning until the map looked equitable.

**[Drag it back to 0.20. Click any ringed site.]**

> And every ranking explains itself — each factor, its percentile, its weight, what it
> contributed, cross-checked against the pipeline's own SHAP driver. No black box.

**[Evidence coverage tab]**

> Last thing. Green is ranked, grey is measured but too thinly to trust — thirty-eight
> thousand tiles — and the white space was never measured at all. Ookla is crowdsourced,
> so the least-connected places generate the fewest speed tests.
>
> We report that as a finding. A clean map would have scored better and meant less.

**[Country dropdown → Indonesia. Wait for it to draw.]**

> Same code. Different file.

**[Stop. Hands off the trackpad.]**

*If you're running long, cut the site-inspector click. Never cut the access-weight beat —
it's the strongest ninety seconds you have.*

---

## Q&A — you own these

Answer in one breath, then stop. Trailing off into a second explanation reads as doubt.

**"How do you know these sites are off-grid?"**
> We don't. It's inferred from night-lights and distance to power and roads, so every row
> is a candidate that triggers a survey — that's on the screen and in the method tab.
> What it saves is the cost of surveying everything.

**"Isn't Ookla data biased?"**
> Badly, and against us — remote sites generate the fewest tests. We apply a minimum
> activity threshold, and we publish the coverage gap as a slide rather than a footnote.
> A tool that hides its blind spots is worse than no tool.

**"HOMER Pro already does this."**
> HOMER Pro is better than us at what it does — bottom-up microgrid design for one site.
> We're the layer above: which sites are worth an engineer's time. We produce the
> shortlist HOMER Pro then models properly.

**"Why is your top site next to a road?"**
> Because we rank easy access higher — mobilisation cost dominates at screening stage.
> It's also why East Malaysia gets zero percent of the shortlist, which we showed you
> rather than hid. It makes this a first-wave list, not a complete one, and the hardest
> sites need an instrument that prices helicopter access instead of penalising it.

**"So your tool fails at the thing it's for."** *(the hostile version — stay calm)*
> At the default weighting, for the hardest region, yes — and we'd rather be the team
> that found that than the team that shipped it quietly. The weight is exposed, the
> effect is one slider, and the cost of fixing it is 0.4% of the carbon. That's a
> policy decision for MCMC to make with the number in front of them, which is exactly
> what a screening tool should produce.

**"What's your R²?"**
> 0.60 out-of-block for Malaysia against 0.76 in-sample, on the population the model is
> validated for. The gap is the honest cost of spatially blocked validation — random
> splits would have flattered us by fifteen points. *(Indonesia is 0.44. Don't mix them
> up.)*

**"Why does the Model tab say R² is minus one point one seven?"** *(if they read the warning)*
> Because that's the model applied outside its design population. It's trained on the
> underserved-target tiles; the export also predicts the wider sufficient-evidence set,
> which includes urban tiles an order of magnitude faster than anything in training, and
> there it's worse than predicting the mean. So we don't let it drive the shortfall term
> — those tiles score zero on it rather than being ranked on an extrapolation. We
> checked, and both choices give an identical top fifty. We took the defensible one and
> put the bad number on screen.

**"Where did the carbon numbers come from?"**
> GSMA's published figures for off-grid telecom sites — thirteen thousand litres of
> diesel a year, 2.63 kilos of CO₂ per litre, 65% abatement from solar-hybrid. 22.2
> tonnes avoided per site. Every constant is in the Method tab with its source.

**"Did you validate the data you were given?"** *(if it comes up — this is your best card)*
> We did, and we rejected a version of it. An earlier re-export fixed the confidence
> tiers but collapsed the model — on identical rows, same site IDs, same measured speeds,
> R² went from 0.59 to minus 8.7, because the training set had become 73% tiles with a
> median of three speed tests. We sent it back, it was fixed the same day, and what
> you're looking at is the corrected version. Every step is in the Data integrity tab.

---

## If something breaks

**Map won't load** — switch to the second browser tab. If that fails too, open
`fig_priority.png` full screen and keep talking. Nobody scores your wifi.

**App is slow to redraw** — keep talking over it. Silence makes three seconds feel like
twenty.

**You lose your place** — go to Evidence coverage. It's the strongest thing you have and
it works as a standalone point.

---

## Things not to say

- **"Towers."** They're tiles. Someone will check.
- **"This site is off-grid."** Say *likely* off-grid, or candidate.
- **"No coverage here."** Say *no measurement* here.
- **"We didn't have time to..."** Nobody did. It reads as an apology for work you
  actually finished.
- Don't claim all seven ethics dimensions are green. Three are amber, and saying so is
  the point of having the tab.

---

## Rehearse it

Twice, out loud, with a stopwatch. Not in your head — in your head you never fumble the
slider, and on stage you will. The Kuala Lumpur beat is the one worth getting smooth:
drag, pause, let them see it, *then* speak.
