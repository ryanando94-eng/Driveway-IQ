# Brisbane Design Jobs

A job search kit for building design, drafting, Archicad / BIM, drafting and design
management, and product development roles in Brisbane and South East Queensland.

It has two parts.

## 1. Web app (`brisbane_design_jobs.html`)

Live version: https://claude.ai/artifact/VD2iXmbgWAr1qGRkysPPAp

| Sheet | What it does |
| --- | --- |
| **A-101 Job feed** | A news feed of current Brisbane and South East Queensland ads, newest first and grouped by day. Ads added since your last visit are marked **New**. If ads arrive while you're reading, an "N new ads" button appears at the top. Each ad has *Open ad*, *Find on SEEK*, *Track* and *Not for me* buttons. The status line shows when the feed last updated and when the next check runs. On claude.ai, the owner also gets a *Check now* button. |
| **A-102 Search** | Choose role families and titles, location, radius, date posted and work type. It builds a grid of ready-made searches on SEEK, Indeed, LinkedIn, Google Jobs, Jora, Adzuna and CareerOne, with one row per role family. It also gives you a boolean string to paste into saved searches, plus 12 niche and government boards. |
| **A-103 My applications** | A private tracker with the stages Saved → Applied → Interview → Offer → Closed, follow-up reminders and notes. On claude.ai it syncs to your account. Opened as a local file, it saves in the browser. |
| **A-104 Employers & boards** | 90+ South East Queensland employers, boards and recruiters: home builders, developers, commercial builders, modular builders, product manufacturers, councils and recruiters. Each has a careers link plus SEEK and LinkedIn searches. |
| **A-105 Ad check** | Paste a job ad. It shows the requirements you already cover, the gaps, salary, years of experience and the keywords to repeat in your resume. On claude.ai it can also draft resume bullets and a cover letter opening for that ad. |

### How the feed updates itself

A Claude routine called **Brisbane design jobs feed** runs every day at 6:52 am and 12:52 pm
Brisbane time. Each run starts a fresh Claude session that:

* searches SEEK, Indeed, LinkedIn, Jora, Hatch, LiveHire, SmartJobs and builders' careers pages for new ads;
* adds new ads to the page's `leads` collection, without duplicates;
* marks ads older than 30 days as stale and clears them after 60 days;
* records the run in `meta/feed`.

Pages open at the time update straight away. When a run finishes, Claude can also send a
notification to your phone.

To change the schedule or pause it, open claude.ai → Routines. The page reads the check times from
`meta/feed`, so update `times` there to match.

Board URL formats were checked in October 2026. SEEK's search now runs on `au.seek.com`.

## 2. Live listings tool (`brisbane_design_jobs.py`)

This pulls ads from the official Adzuna and Jooble job-search APIs into one table. The table is
ranked by fit, has duplicates removed and flags ads that are new since your last search. You can
export the results to CSV or HTML.

```
python brisbane_design_jobs.py              # opens the window (or press F5 in IDLE)
python brisbane_design_jobs.py --cli --days 7 --csv jobs.csv
python brisbane_design_jobs.py --cli --locations Brisbane "Gold Coast" --html jobs.html
python brisbane_design_jobs.py --links      # print board search links, no keys needed
```

* It uses only the Python standard library, so there is nothing to install. It needs Python 3.8+ with tkinter for the window.
* For live listings you need free API keys:
  * Adzuna: https://developer.adzuna.com/signup gives an `app_id` and `app_key`.
  * Jooble: https://jooble.org/api/about gives an API key.

  Enter them under **API keys…**, or set `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` and
  `JOOBLE_API_KEY`. Keys are saved to `brisbane_jobs_config.json` next to the script. That file
  is git-ignored.
* **Open board searches** works without keys. It opens SEEK, SEEK's Architectural Drafting
  category, Indeed, LinkedIn and Google Jobs for your selected roles.
* The fit score (0–100) comes from:
  * a title match, such as drafting manager, building designer or Archicad;
  * Archicad and residential context in the ad;
  * a South East Queensland location;
  * how recently it was posted.

  Civil, mechanical and electrical drafting ads lose points, and so do product-manager roles
  outside building.
* Adzuna's free tier allows about 25 calls a minute. The tool spaces its calls to stay under
  this limit.

Run the tests (no network needed):

```
python -m unittest job_search/test_brisbane_design_jobs.py
```
