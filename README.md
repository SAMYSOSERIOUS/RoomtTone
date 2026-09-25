# Roomtone

*Room tone* is what sound editors record when nobody in the room is speaking. Roomtone measures what a conversation sounds like when nobody real is in it.

**How much human attention on social media goes to machines, and can we give it back?**

Roomtone counts the human replies and likes that land on automated-looking accounts, the trends that only look popular, and the mood shifts that machines start.
It publishes the numbers as group totals, forecasts tomorrow, and ships the fix as a Bluesky feed with
the ghosts removed. It never names an account.

## What it does

| Piece | Module | Output |
|---|---|---|
| Collect posts, replies, likes, deletes from Bluesky's free live stream | `roomtone/collect.py` | `data/events.parquet` |
| Privacy gate: pseudonyms, opt-outs, honoring deletes, retention limits | `roomtone/privacy.py` | same table, safe |
| Account habits: rhythm, sleep gap, regret rate, sign-up wave, AI phrases | `roomtone/features.py` | one row per account |
| Automated-looking score (0 to 1) with a published false-alarm rate | `roomtone/score.py` | `scores.parquet` |
| Wasted Breath Index, real trending list, immune response time | `roomtone/metrics.py` | `results.json` |
| Ghost forecast for tomorrow, graded against "tomorrow = today" | `roomtone/forecast.py` | in `results.json` |
| Who steers whom: time zone of origin, audience x topic, mood lead-lag verdicts, origin -> audience -> destination flow | `roomtone/steering.py` | in `results.json` |
| Sub-topics with privacy-gated example posts | `roomtone/subtopics.py` | in `results.json` |
| Dashboard data file for the app | `roomtone/rt_export.py` | `app/rt.js` |
| Older self-contained report page | `report/build_report.py` | `report/roomtone.html` |
| Ghost-free feed: a Bluesky custom feed skeleton | `roomtone/feed.py` | feed server |
| Dashboard | `roomtone/dashboard.py` | Streamlit site |

## Run everything in one command (practice data, no accounts needed)

```bash
pip install -r requirements.txt
scripts/run_all.sh                 # simulate 4 sources -> pipeline -> rt.js -> unpack the dashboard
cd app && python -m http.server 8080   # open http://localhost:8080
```

## Step by step

| Step | Command | What it does |
|---|---|---|
| 1 | `python -m roomtone.collect --simulate --hours 72 --source bluesky` | Practice stream for one platform (also `mastodon`, `reddit`, `youtube`) into `data/<source>/` |
| 2 | `python -m roomtone.pipeline bluesky mastodon reddit youtube` | Privacy gate, habits, score, Wasted Breath, real trends, steering, sub-topics, forecast per source |
| 3 | `python -m roomtone.rt_export` | Writes `app/rt.js`, the one data file the dashboard reads (all sources, aligned) |
| 4 | `python tools/unpack_design.py design/Roomtone_Dashboard.html` | Unpacks the Claude Design export into `app/` and points it at `rt.js` |
| 5 | `cd app && python -m http.server 8080` | Serves the dashboard locally |
| tests | `python -m pytest -q` | Privacy gate and metric checks |

## Go live

```bash
python -m roomtone.collect --hours 1 --source bluesky            # free, no sign-up
export REDDIT_ID=... REDDIT_SECRET=...   # free app at reddit.com/prefs/apps, non-commercial
python -m roomtone.collect --hours 1 --source reddit
export YOUTUBE_KEY=...                   # free Google API key
python -m roomtone.collect --hours 1 --source youtube
python -m roomtone.collect --hours 1 --source mastodon          # public timelines, no key
python -m roomtone.pipeline bluesky mastodon reddit youtube && python -m roomtone.rt_export
```
`scripts/run_live.sh` does all of that; put it in cron hourly and the dashboard's "last run" moves with it.
Sources collected for real show a LIVE badge; sources still on practice data show PROTOTYPE.

## Changing the design

Edit the dashboard in Claude Design, export it as one HTML file, drop it over `design/Roomtone_Dashboard.html`
and re-run step 4. The unpacker applies three patches so the app reads `rt.js`: per-source datasets, sub-topics
with example posts, and the local world map. Everything else in the design is untouched.

## Privacy rules built into the code

- Account names are replaced by a keyed pseudonym before anything is stored (`ROOMTONE_KEY`).
- Delete events remove the matching stored post within the next purge run.
- Accounts in `data/optout.txt` are dropped at the gate.
- Raw text is kept 30 days, features 90 days (`privacy.purge`).
- Results are published only for groups of at least 50 accounts (`MIN_GROUP`).
- The feed hides posts; it never labels anyone.

## Layout

```
roomtone/
  collect.py    live stream client + simulator
  privacy.py    pseudonyms, opt-outs, deletes, retention
  features.py   account habits
  score.py      automated-looking score
  metrics.py    Wasted Breath Index, real trends, immune time
  forecast.py   tomorrow's ghost share, self-graded
  steering.py   time zones of origin, audience x topic, mood lead-lag, where they push
  feed.py       Bluesky custom feed skeleton
  pipeline.py   runs everything, writes results.json
  dashboard.py  Streamlit dashboard
  subtopics.py  sub-topics, attention lost per sub-topic, privacy-gated example posts
  sources.py    real collectors for Mastodon, Reddit and YouTube
  rt_export.py  writes app/rt.js in the dashboard's data shape
app/            the dashboard (unpacked Claude Design export + rt.js)
design/         the Claude Design export, as delivered
tools/          unpack_design.py
tests/          pytest checks for the privacy gate and the metrics
```

Practice data is generated by `collect.py --simulate`; it is not real accounts.

## The steering test, in plain words

For every audience language and topic with at least 50 real people:

1. **Mood lines.** Hourly average mood of human posts and of automated posts (a small word list on practice data; swap in the multilingual Cardiff NLP model for real data).
2. **Who turned first.** The first hour each line moves more than 0.3 from its opening level and stays there for 4 hours.
3. **Verdict.** *Steered*: bots turned first and humans followed within 8 hours, with the changes correlated. *Against locals*: bots sit on the other side of zero from humans by more than 0.4 and humans did not follow. *Mirror*: nobody turned and the lines sit within 0.25. *Clean*: almost no automated accounts.
4. **Where from, where to.** Time zone of origin from each account's quiet hours (published only as regions), the audience it writes to, the direction it pushes, the sites it links to compared with real people, and how many real people it replied to.

"Bots moved first" is timing, not proof of cause. The report says "came before," never "caused."

## All sources, integrated

Every source runs through the same collector interface, privacy gate, score and checks. `rt_export.py` then builds
one combined dataset itself (`data/all_sources.json`): engagement-weighted shares, summed counts, example posts from
every platform, plus the **contagion clock**: which platform the campaign hit first and how many hours the others
lagged, judged against each platform's own baseline. The dashboard's "All sources" view reads that dataset.
A source shows **Live** once it has been collected from the platform, **Practice** while it runs on the simulator.

## The floating gallery

`app/float.js` adds a band to the dashboard: example automated-looking posts from every source drifting like pinned
screenshots. Names and avatars are black bars, personal details in the text are black bars (from `redact.py`), stock
phrases are highlighted, and each card shows its platform, time, language, score, signals and the human engagement it
drew. Nine cards are visible at a time; the rest fade through. Hover holds a card. Reduced-motion users get a still layout.

## Example posts and privacy

The dashboard shows example posts inside a sub-topic. Rules, enforced in `subtopics.py`:
only posts by accounts scoring 0.9 or higher; on real data only texts that at least 3 different accounts
posted (copy-paste campaigns), never a sentence one person wrote; no handle, avatar, pseudonym or clickable
link; stock phrases marked so the reader sees why it was flagged. Personal details inside the text (emails, @handles,
phone numbers, IBANs, street addresses, personal names) are replaced by black bars before anything is written
(`redact.py`); links keep the domain only. The first example in each sub-topic is one that needed redaction, so the
rule is visible.
