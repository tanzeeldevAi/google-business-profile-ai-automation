<div align="center">

# GBP Autopilot — Audit, Fix and Run a Google Business Profile

**Scores a Google Business Profile against 57 local SEO rules, writes a client-ready report,
fixes what it can through the API, answers every review, posts weekly, sets holiday hours, and
tells you the moment Google changes something behind your back.**

For the local business that ranks in the map pack or doesn't get the call.

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![Google Business Profile API](https://img.shields.io/badge/Google-Business%20Profile%20API-4285F4?logo=google&logoColor=white)](#step-2--get-google-api-access-the-slow-bit)
[![Tests](https://img.shields.io/badge/tests-623%20passing-brightgreen)](#step-4--prove-it-works-before-touching-a-live-profile)
[![Developed by Tanzeel](https://img.shields.io/badge/Developed%20by-Tanzeel-6C3EF5)](https://github.com/tanzeeldevAi)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](#contributing)

</div>

---

## What is this?

A Google Business Profile is the highest-value free asset a local business owns, and almost every
one of them is half-finished. No secondary categories. A two-line description. Reviews from 2023
with no reply. No post since the profile was created. Nobody notices, because nothing looks broken
— the phone just rings less than the competitor's.

This finds all of it, tells you what it costs in plain words, and then does the parts a computer
can legitimately do.

```
  their website ──┐
                  ├──► audit ──► report ──► fix      (description, holiday hours)
  their profile ──┘        │            └──► reviews  (reply to every one)
                           │            └──► post     (from a service page you name)
                           └──► watch              (Google changed something)
```

Connect a profile and it reads the business's own website too, so everything it writes uses their
real service names and real wording rather than a category label.

**Everything that writes is a dry run unless you add `--apply`.** You always see the exact before
and after first.

---

## What it checks

57 rules across fourteen areas, each weighted by what it actually costs you:

| | |
|---|---|
| 🩺 **Profile health** | Verified, open, no edits stuck in review, not flagged as a duplicate |
| 📛 **Name, address, phone** | Complete NAP, service areas, website, social profiles, and a check on whether the name looks keyword-stuffed — the most-reported violation there is, and the penalty is suspension, not a ranking dip |
| 🗂️ **Categories** | Primary set, secondary categories used (most profiles leave all nine empty), not over-stuffed |
| 📝 **Description and services** | Written, long enough, no URLs or offers (Google strips them), names the service and the city, services listed and described, **service names carry the area, descriptions have real depth**, attributes filled, booking link |
| 🕗 **Hours** | Set, complete for the week, and holiday hours set ahead |
| 📸 **Photos** | Enough of them, added recently, **still arriving each month**, at least one video |
| ⭐ **Reviews** | Count, rating, **response rate**, nothing left waiting, still coming in, and whether the owner's replies say anything worth indexing |
| 📣 **Posts** | Posted in the last 7 days, posting regularly, every post has a button, **and the button goes to the right page not the home page** |
| ❓ **Q&A** | Nothing unanswered, common questions seeded by the owner |
| 🌐 **Website** | Reachable, the profile's phone actually appears on it, LocalBusiness schema present, **enough pages to back the services and areas** |
| 🔎 **Search terms** | The words people actually typed to find the profile, and whether the profile says any of them |
| 🥊 **Against your competitors** | Reviews, photos and categories versus the businesses actually ranking above you *(needs DataForSEO)* |
| 📒 **Directory listings** | Whether other directories show the same phone number *(needs DataForSEO)* |
| 📈 **Performance** | 90 days of views and actions from Google's own data |

Each finding says what was found, **why Google cares**, and **what to do about it**. That is what
makes the report worth sending to a prospect rather than just reading yourself.

> **A section it could not read is reported as "not checked", never as a failure.** Telling a
> business their photos are missing when you were simply not allowed to look is how an audit loses
> its credibility.

---

## What it fixes automatically

| Command | What it does |
|---|---|
| `run.py fix` | Rewrites the description; sets holiday hours; **turns the search terms the profile ignores into named services** |
| `run.py reviews` | Replies to unanswered reviews in the owner's voice. Low-star reviews are **held for a human** by default |
| `run.py post` | Writes and publishes a Google Post, rotating through the services on the profile |
| `run.py watch` | Fingerprints the profile and reports anything that changed since last time |
| `run.py keywords` | The search terms Google reports, and which ones the profile never mentions |
| `run.py compare` | Who is beating you in the map pack, and by how much |
| `run.py citations` | Whether directories agree with the profile's phone number |
| `run.py site` | Shows what was read from the business's own website |
| `run.py dashboard` | A local web UI for all of the above |

**It never invents a fact.** The description and posts are built only from what is already on the
profile plus the `facts` you list in `config.yaml`. It will not claim a founding year, a
certification, an award, a guarantee or a price it was not given, because that ends up on a public
profile under a real business's name.

---

## Requirements

- **[Python 3.10 or newer](https://python.org/downloads)** — on Windows, tick **"Add Python to PATH"**
- **A Google account that manages the Business Profile** (owner or manager)
- **A Google Cloud project with Business Profile API access** — this is the slow part, see Step 2
- **A Claude subscription** with the [Claude Code CLI](https://docs.claude.com/en/docs/claude-code)
  signed in, **or** an `ANTHROPIC_API_KEY`

> Writing runs through the Claude CLI on your **existing subscription** by default, so there is no
> API key and no per-review bill.

---

## Install — step by step

### Step 1 — Download and install

```bash
git clone https://github.com/tanzeeldevAi/google-business-profile-ai-automation.git
cd google-business-profile-ai-automation
pip install -r requirements.txt
```

### Step 2 — Get Google API access (the slow bit)

Google does not hand out Business Profile API access automatically. Budget a few days.

1. Create a project at <https://console.cloud.google.com/>
2. **APIs & Services → Library**, and enable each of these:
   - Google My Business API *(the legacy one — reviews, posts and photos live here)*
   - My Business Business Information API
   - My Business Account Management API
   - Business Profile Performance API
   - My Business Q&A API
   - My Business Place Actions API

   > The Performance API is the one that carries the search terms. Without it
   > you lose the single most useful part of the audit, so do not skip it.
3. **Request access.** Fill in Google's
   [Business Profile APIs access form](https://developers.google.com/my-business/content/prereqs).
   Approval takes anywhere from a day to a couple of weeks.
4. **OAuth consent screen** → set it up → then **PUBLISH APP**.

   > ⚠️ **Do not skip publishing.** While the consent screen is in **Testing**, Google expires your
   > login every **7 days**, and the tool dies with `invalid_grant` every week. You do **not** need
   > Google to verify the app for your own use — publishing alone stops the expiry. This is the
   > single most common thing people get stuck on.

5. **Credentials → Create credentials → OAuth client ID → Desktop app → Download JSON.**
   Save it as **`data/client_secret.json`**.

> If step 3 has not come through yet, the tool still works. The Business Information APIs are
> usually available immediately, so you get the profile, categories, hours and description audit
> straight away — reviews, posts and photos report as "not checked" until v4 access lands.

### Step 3 — Configure

```bash
copy config.example.yaml config.yaml      # Windows
cp   config.example.yaml config.yaml      # macOS / Linux
```

Open `config.yaml` and fill in the **`business:`** block. The `facts:` list is the only place the
writer may take claims from, so keep every line true and checkable.

### Step 4 — Prove it works before touching a live profile

```bash
python test/test_rules.py     # 186 checks: every rule, on a good profile and a broken one
python test/test_site.py      #  63 checks: website reading, discovery, grounding guard
python test/test_keywords.py  #  84 checks: search terms, coverage, clustering
python test/test_competitors.py # 70 checks: map-pack comparison, NAP consistency
python test/test_dashboard.py   # 70 checks: the dashboard's command whitelist and path guards
python test/smoke_test.py     # 150 checks: audit, report, fixes, reviews, posts, watcher
```

**623 checks, entirely offline.** No Google account, no network, no model calls. Run these before
every deploy — it is much cheaper than finding out on a client's profile.

### Step 5 — Sign in

```bash
python run.py login
python run.py doctor
```

`doctor` checks your config, your login age, the Claude CLI and live API access, and touches
nothing. Fix anything it flags before going further.

### Step 6 — Find the profile

```bash
python run.py locations
```

If the account manages more than one, paste the account and location into `config.yaml` under
`location:`, or pass `--location` on every command.

### Step 7 — Audit

```bash
python run.py audit
```

You get the score in the terminal and a self-contained HTML report in `reports/`. Open it in a
browser, print to PDF, send it.

**That's it — you're running.** 🎉

---

## Daily use

```bash
python run.py fix                 # see the exact before and after
python run.py fix --apply         # write it

python run.py reviews             # draft replies, show them, send nothing
python run.py reviews --apply     # send them

python run.py post                # next service in the rotation, shown not sent
python run.py post --url https://yoursite.com/services/boiler-repair/
python run.py post --apply        # publish it

python run.py keywords            # what people typed to find this profile
python run.py site                # what was read from the website

python run.py watch               # what changed since last time
python run.py daily --apply       # watch + audit + reviews, in order
```

`daily` is the one to schedule. On Windows use Task Scheduler; on a server, cron:

```bash
15 9 * * * cd /opt/gbp-autopilot && python run.py daily --apply >> logs/daily.log 2>&1
```

---

## The dashboard

If you would rather click than type:

```bash
python run.py dashboard
```

```
  Dashboard: http://127.0.0.1:8770
  Everything is a DRY RUN until you turn on Apply.
```

The score and its history, open alerts, a button for every command, and the output streaming back
live as it runs. It shells out to this same CLI rather than reimplementing anything, so the two
can never disagree about what a command does.

Four things it enforces:

- **Dry run is the default.** Publishing needs the Apply switch turned on deliberately, it asks
  you to confirm by business name, and **it resets itself after every run**.
- **One job at a time.** Two commands writing to the same profile at once is how you get
  half-applied changes. A second request is refused, not queued silently.
- **The browser never assembles a command.** It names one from a whitelist, and each command
  accepts only its own flags. `login` is deliberately not exposed — it opens a browser and waits,
  which a web request cannot do.
- **Localhost only.** Bound to `127.0.0.1` with no auth. Point it anywhere else and it demands
  `--token` first, because it holds a live Google login for somebody else's business.

## Comparing against whoever is actually ranking

Every other rule here judges a profile against a fixed number: 20 photos, 25 reviews, 4.0 stars.
Those are a guess at an average market, and in a real one they are usually wrong in both
directions. Twenty-five reviews is invisible in central London and dominant in a market town.

```bash
python run.py compare --keywords "plumber durham, boiler repair durham"
```

```
  WHERE YOU RANK
    plumber durham                           #7
    boiler repair durham                     not in the top results

  THE TOP 3 IN THAT PACK
    #   BUSINESS                          REVIEWS  RATING  PHOTOS
    1   Riverside Plumbing                    412     4.8     180
    2   City Drains Ltd                       286     4.6     120
    3   Quick Fix Plumbers                     95     4.2      60
    ---------------------------------------------------------------
    you Northgate Plumbing                     30     4.9      24

  THE GAP
    Reviews    you       30   top-3 average      264   234 behind
    Rating     you     4.90   top-3 average     4.53   0.37 ahead
    Photos     you       24   top-3 average      120    96 behind

  CATEGORIES THE TOP 3 USE THAT YOU DO NOT
    Boiler supplier                          used by 2 of 3
```

Three rules come from this: **X1** reviews vs the top-3 average, **X2** categories two or more of
them use that you don't, **X3** photos vs the top-3 average. The same 30 reviews **passes** in a
market where the top three average 25 and **fails** where they average 400 — which is the whole
point, and there's a test for exactly that.

Google's own API will only ever describe profiles *you* manage, so this is the one feature that
needs a paid third party ([DataForSEO](https://dataforseo.com)). Without credentials, X1/X2/X3
report "not checked" and nothing else changes. One billed request per keyword, capped at five,
cached for 24 hours.

Two things worth knowing:

- **Competitors' post cadence and review velocity are not compared**, because no third party
  exposes them. X3 compares photos and says so, rather than being named after something broader
  than it measures.
- **Aggregator entries are filtered out.** Some map results are directory pages rather than
  businesses; averaging your reviews against one of those is meaningless.

## Do the directories agree with you?

```bash
python run.py citations
```

Finds the business on known directories and checks the phone number on each against the profile.

```
    DIRECTORY                  PHONE SHOWN
    yell.com                   01915550142
    yelp.com                   01915559999
    cylex-uk.co.uk             no phone shown
    checkatrade.com            unread (returned 403)

  1 listing(s) show a DIFFERENT phone number to your Google profile:
    yelp.com  shows 01915559999
```

A page with **no** phone visible is reported as "not shown", never as a mismatch — plenty of
directories hide the number behind a click, and calling that an inconsistency would be a
fabricated finding. A page we can't read is reported as unread.

The directory list in `citations.py` is weighted towards the UK, US and Gulf. If a market uses
directories that aren't in it, the tool says so rather than reporting a clean run — and if nothing
could be read, it says *that* too, instead of "every readable listing agrees", which is technically
true of an empty set and reads as a clean bill of health.

> **There is deliberately no citation-count rule.** "Get listed on 40–50 directories" is a number
> that gets repeated in training material and sold by citation vendors. Consistency across the
> listings you have is a real ranking factor; volume past the main aggregators is not, and scoring
> a profile down for having 30 listings instead of 50 would be inventing a problem. There's a test
> asserting no such rule exists.

## The words people actually typed

Google's Performance tab has a list called **"Searches showed your Business Profile in the search
results"** — the exact phrases real customers used. It is the most valuable thing on the profile
and almost nobody acts on it.

This pulls the whole list through the API and does the obvious thing with it:

```bash
python run.py keywords
python run.py keywords --csv     # full list to reports/, for a client
```

```
  TERM                                            SHOWN   WHERE IT APPEARS
  ----------------------------------------------------------------------------
  plumber durham                                    820   categories, description
  emergency plumber durham                          260   services
  boiler repair durham                              175   NOWHERE
  power flush durham                                <15   NOWHERE

  Non-brand terms: 12   covered by the profile: 58%
  5 term(s) appear nowhere on the profile, worth 1,375 impressions.
```

Every term is cross-referenced against the business name, categories, description, services,
recent posts and the website. The ones marked **NOWHERE** are the work: Google is already showing
this business for words the profile never says.

Then turn them into services:

```bash
python run.py fix --only services              # see the proposals
python run.py fix --only services --apply      # write them
```

It clusters the variants ("boiler repair", "boiler repair near me", "emergency boiler repair" are
one service), names each one in the customer's own words, and writes a real description from the
website copy. The same terms are fed to the post writer, so they get used on an ongoing basis too
— the services list is the permanent half, posts are the ongoing half.

> ⚠️ **Read every proposal before applying.** A search term proves people *looked* for something.
> It does not prove this business *offers* it. A service on a public profile is a promise, and
> "24 hour emergency callout" showing up in the search data does not mean they do one. The tool
> shows you which search terms justified each proposal, and says this in the output every time.

Three things it handles that a naive version gets wrong:

- **Threshold counts.** Google returns an exact number for big terms and "fewer than 15" for the
  rest. Most terms are the latter. They are kept and ranked below exact counts, because a
  long-tail phrase with real intent is not worthless.
- **Brand searches.** Searches for the business by name are separated out. A coverage score that
  counts your own name is flattering and useless.
- **The city.** "boiler repair durham" is covered by a service called "Boiler repair" on a profile
  that is already in Durham. Demanding the city appear too would report gaps that are not real.

## Posting about specific services, from your own pages

By default posts rotate through the services listed on the Google profile. That works, but the
writer only has a service *name* to go on.

Give it your service page URLs instead and it gets the real thing:

```yaml
website:
  service_pages:
    - "https://northgateplumbing.co.uk/services/boiler-repair/"
    - "https://northgateplumbing.co.uk/services/blocked-drains/"
    - "https://northgateplumbing.co.uk/services/bathroom-installation/"
```

Now posts rotate through **only those services**, one per run, least recently used first, and each
post is written **from that page**: the same scope, the same inclusions, the same process, the same
areas, the same names for things.

```bash
python run.py post                      # next service in the rotation
python run.py post --url https://...    # post about this one specifically
```

**The details have to match the page.** That is enforced, not just asked for:

- Every number in the draft is checked against the source page and your confirmed `facts`.
- A price, timeframe, percentage or quantity that is not there gets the post **rewritten without
  it** — not swapped for a different invented number.
- After three attempts it **refuses to publish** and tells you why. `--force` overrides, if you
  have read it and you are happy.

The source page also feeds the image prompt, so the picture reflects what that job actually
involves rather than a generic stock scene.

## Reading the website

When you connect a profile, its website is fetched automatically from the `websiteUri` already on
the profile. Nothing to configure.

That one step does three things:

1. **The description rewrite** uses the company's real wording and real service names, instead of
   a category label.
2. **Posts** are grounded in the business's own copy even when no service pages are listed.
3. **Three extra audit checks** become possible: is the site reachable at all, does the phone
   number on the profile actually appear on the site (a NAP mismatch is a real ranking problem),
   and does the site carry LocalBusiness schema.

See exactly what was read — this is worth running once per client, so you know the writer has good
source material rather than hoping:

```bash
python run.py site
python run.py site --refresh     # ignore the cache
```

Pages are cached for a week so a daily run does not hammer a client's server. If the site sits
behind Cloudflare and returns 403, set `website.user_agent` in `config.yaml`.

## Post images

Optional, off by default. Turn it on in `config.yaml` under `images:`.

| Backend | How it works |
|---|---|
| `chatgpt` | Drives a Chrome you are **already logged into**, over the DevTools protocol. No API key, no per-image cost |
| `gemini` | Google AI Studio over HTTP. Free tier, stable, works on a server. Needs `GOOGLE_API_KEY` |
| `none` | No images. Posts still publish, as text |

For the ChatGPT backend, start Chrome like this once and leave it open:

```bash
chrome.exe --remote-debugging-port=9222 --user-data-dir=C:/gbp-chrome
```

Log into ChatGPT in that window. The script attaches to it and never touches your login.

Google Posts take a **public image URL**, not a file, so a generated image has to be hosted before
a post can use it. Set `images.host` to `imagekit` (needs `IMAGEKIT_PRIVATE_KEY`) or `base_url`
(you sync `data/images/` to your own web space).

> ⚠️ **These images go on Posts only.** The tool will not put a generated image in the profile's
> photo gallery and there is no setting to make it. Google's photo rules require photos to
> represent the actual business; a gallery of generated images is a well-trodden route to a quality
> review and a suspension. An illustration on a weekly post is ordinary marketing. A generated
> "photo of our workshop" is not. **Real photos of real jobs beat these every time.**

> ⚠️ Driving ChatGPT through a browser is automated access to a site whose terms do not permit it.
> Your account, your call. The `gemini` backend is the supported path and needs no browser.

---

## Safety

This tool writes to a live public profile that a real business depends on, so:

- **Dry run is the default.** Nothing is written without `--apply`.
- **You see the exact before and after** for every change first.
- **Narrow update masks.** A patch to the description cannot blank the phone number.
- **Nothing is done twice.** Every reply and post is recorded, so a re-run is safe.
- **Low-star reviews are held for a human** by default. An automated reply to an angry customer is
  public forever and reads exactly like what it is.
- **Holiday hours default to closed**, because being wrongly listed as open earns one-star reviews
  from people who drove to a locked door. List the days you trade under `holidays.open_on`.
- **No invented facts**, anywhere, ever.

---

## Troubleshooting

<details>
<summary><b>"Your Google login has expired" every week</b></summary>

Your OAuth consent screen is still in **Testing** mode, where Google expires refresh tokens after
7 days. Publish the app: **Google Cloud Console → APIs & Services → OAuth consent screen → PUBLISH
APP**. You do not need verification for your own use. Then `python run.py login` once more.
</details>

<details>
<summary><b>403 on reviews, posts or photos, but everything else works</b></summary>

Those three live on the legacy **v4** API, which is granted separately from the rest. Your project
has the v1 APIs but not v4 yet. Finish the access form in Step 2.4 and wait. The audit still runs
and reports those sections as "not checked".
</details>

<details>
<summary><b>The audit says everything is fine and I don't believe it</b></summary>

Check the "Not checked" line at the bottom. If most sections could not be read, the score only
covers what was readable. That is deliberate, but it does mean a partial audit flatters a profile.
</details>

<details>
<summary><b>`locations.get` returns almost nothing</b></summary>

The Business Information API requires a `readMask` and silently returns a near-empty object if you
ask for too little — which looks exactly like an empty profile. This tool always sends the full
mask, so if you see this you have probably edited `FULL_READ_MASK` in `gbp/api.py`.
</details>

<details>
<summary><b>The description fix keeps getting rejected by Google</b></summary>

Google strips descriptions containing URLs, phone numbers or promotional offers. The generator is
told not to produce them and rule CT3 checks for them, but if you hand-edit the text before
applying, check it again.
</details>

<details>
<summary><b>"Could not attach to Chrome on http://localhost:9222"</b></summary>

Chrome is not running with remote debugging, or it is running with your normal profile. Start a
separate one with `--remote-debugging-port=9222 --user-data-dir=C:/gbp-chrome` and leave it open.
</details>

<details>
<summary><b>No image appeared / ChatGPT selectors broke</b></summary>

It is a real web UI and it moves. Every selector lives in one place: `SELECTORS` in
`gbp/images.py`. The browser is deliberately left open on failure so you can see what happened.
Or switch `images.backend` to `gemini`, which has no UI to break.
</details>

<details>
<summary><b>The watcher says the review count dropped</b></summary>

Google removed reviews. That is usually a filter sweep, sometimes a competitor reporting them, and
occasionally the start of a suspension. Worth checking the same day, which is the entire reason
the watcher exists.
</details>

---

## Layout

```
config.yaml          all tuning and business facts
run.py               the CLI
gbp/
  auth.py            OAuth, token refresh, and the 7-day Testing-mode trap
  api.py             the Business Profile APIs, across all six hosts
  rules.py           THE RULE SET. 57 local SEO rules, each with why and fix
  audit.py           fetches a snapshot, runs the rules, scores it
  report.py          the client-facing HTML report
  fix.py             applies what can be applied, dry-run first
  reviews.py         drafting and sending review replies
  posts.py           writing and publishing Google Posts
  images.py          post images, and where they may not go
  site.py            reads the business's own website, and the grounding guard
  keywords.py        search terms, coverage analysis, clustering into services
  dashboard.py       the local web UI: whitelisted commands, streamed output
  static/dashboard.html
  competitors.py     the live map pack, and the delta against the top three
  citations.py       directory listings and NAP consistency
  dataforseo.py      the one paid dependency, isolated and optional
  holidays.py        which holidays are coming, and which it refuses to guess
  watch.py           change and suspension detection
  llm.py             Claude CLI or API, plus the AI-tell stripper
  db.py              SQLite: idempotence, audit history, alerts
test/                623 offline checks
```

---

## Contributing

Issues and pull requests welcome — especially more rules, more countries in `holidays.py`, and
resilience in the ChatGPT selectors.

If you add a rule, add its pair of tests. A rule that is only ever tested on a failing profile will
happily fail on a good one too, and the first person to find out is a client reading the report.

## License

[MIT](LICENSE) — free to use, change and share. If it helps you, a ⭐ on the repo is appreciated.

---

<div align="center">

**Built by [@tanzeeldevAi](https://github.com/tanzeeldevAi)**

*google business profile · GBP · google my business · local seo · map pack · local search
review automation · review reply · google posts · citation · NAP · local ranking
python · claude ai · seo audit · seo automation · agency tools · GMB API*

</div>
