# allabiografer.se

A static site aggregating cinema screenings across Sweden. Reimplementation of [allekinos.de](https://allekinos.de/) by [Nikita Tonsky](https://tonsky.me/) for the Sweden.

## Usage

Screenings, movies, films and venues live in `data/allabiografer.db`; posters in `data/posters/` — `{tmdb_id}.jpg` for TMDB, `{source}/{title}.jpg` for posters taken from a cinema's own site.

Parse screenings from all supported cinemas:

```
mise run parse
```

Successful non-empty parses replace each source's screenings from today onward
(Europe/Stockholm), removing cancelled or rescheduled listings. Screenings on
past dates are retained. Failed or empty parses keep the previous programme.

Parse Folkets Hus och Parker (Bio Roy in Göteborg, Spegeln in Malmö, Röda Kvarn
in Helsingborg):

```
mise run parse:folkets_hus_och_parker
```

This replaces `bioroy_se`; its screenings from today onward are replaced on a
successful run, while past dates are retained.

Parse Cinemascenen (Ystad, Katrineholm, Strängnäs, Söderhamn, Hudiksvall):

```
mise run parse:cinemascenen_se
```

Build the static site:

```
mise run build
```

Serve locally:

```
mise run serve
```

Screenings store typed content versions, presentation, and accessibility in JSON
columns. Film languages belong to film metadata. Missing audio, subtitles,
dimension, and projection remain unknown; explicit no subtitles is distinct.

Programme blocks group compatible content and presentation facts, including all
screening modifiers. Atmos, 4K, Laser, VIP, XL, and audio description each define
distinct variants. Overlapping spoken-language facts merge; disjoint facts and
ambiguous screenings stay separate. Unknown subtitle facts have no heading;
explicit no subtitles remains distinct. The standard presentation has no label.

Legacy screening databases require a fresh parse; no data migration runs.
Parse into a new database with `parse --output /path/to/new.db <parser>`.

## Deployment

Deployed to [Fly.io](https://fly.io).

```
fly deploy
```

## Festivals

Festival planners live at `/festival/{slug}/{year}/`. Editions are defined in
`src/parse/festivals.py`; their screenings are stored in the `festivals` and
`festival_screenings` tables, independently of the regular two-week cinema
programme. Times include explicit UTC offsets.

Refresh programmes with `mise run parse:festivals` (also included in
`mise run parse`), then build normally. Importers read the festivals' public
APIs, selected by each edition's `source`:

- `stockholm`: dated screenings with a festival section. End times use film
  runtimes and exclude talks and travel.
- `prisma` (Göteborg Film Festival): films and short-film packages; happenings
  are excluded.

The planner supports selections, a personal calendar, overlap warnings, shared
URLs, and downloaded iCal files. Selections are stored in the URL and locally
in the browser for each festival edition. Explicit selections in a shared URL
replace the saved selection; otherwise, the saved schedule is restored.
Calendar exports are snapshots; export again after programme changes.

Run planner logic tests with `node --test tests/festival.test.cjs`.

## Weekly newsletter

The `Newsletter` GitHub Actions job prepares city editions on Thursdays at
09:00 Europe/Stockholm (GitHub may start scheduled jobs late). PostHog owns the
audience, verified sender, marketing opt-outs, suppression, and delivery metrics.
Python compares upcoming screenings against 30 days of history, supplies structured movie data, and starts city batches.
The PostHog library template owns the subject, HTML, plain text, and all wording.
No subscriber addresses are downloaded to GitHub or committed to this repository.

The city-page form uses single opt-in: browser JavaScript sends `newsletter_signup`
directly through the existing `/salong` PostHog proxy using the public project token.
It uses a normalized email identity, sets `email` and `newsletter_confirmed = yes`,
and adds `newsletter_subscribed_city_<city> = yes` without replacing other cities.
It does not attach the email to the anonymous analytics identity or clear marketing opt-outs.
No additional signup backend or private browser credential is needed. Build with the
existing `POSTHOG_PROJECT_TOKEN` and `POSTHOG_HOST` arguments; without them signup stays disabled.
The form links to `/nyhetsbrev/` for subscription and privacy information.

Python discovers cities from these membership properties and the legacy
`newsletter_city` property among opted-in subscribers with a nonempty email.
Addresses stay in PostHog. City values must
match scraped city names exactly; unknown cities fail before any batches start.
New subscribed cities need no GitHub configuration or separate template workflow.

Use one **active**, unscheduled PostHog delivery workflow: event trigger → one native
email → exit. It listens for `newsletter_edition_ready` and its ID is
`01a1408b-a71f-0000-c69b-722f68f522a8`.
Its flat, AND-combined audience filters require `newsletter_confirmed` equal to
the string `yes`, set on explicit single-opt-in signup. Do not restrict the
city in this shared workflow: Python creates two batch dispatchers with those filters,
one for legacy `newsletter_city = edition city` and one for
`newsletter_subscribed_city_<edition city> = yes`. Each captures one event per matching
person with the edition in `event.properties.newsletter`. The delivery workflow
renders that event and enforces marketing opt-outs. Recipient addresses stay in PostHog.
The shared workflow must deduplicate `{person.id}:{event.properties.newsletter.city}:{event.properties.newsletter.start}`
for at least seven days, without a threshold. This prevents duplicate delivery when
a person matches both audiences, while allowing one edition for each subscribed city.

Select a verified sender and a **marketing** message category. Leave the recipient
as `{{ person.properties.email }}`, without CC/BCC. Optional audience filters and
email sending rate limits remain on the shared delivery workflow. Select the library template
`01a138fb-15dd-0000-72dc-6b0dc068ba35` on the email action (`config.template_uuid`).
Template-library edits do not automatically update the delivery workflow's snapshot:
update and publish its email action in PostHog after changing the library template.
The template reads `event.properties.newsletter`: `city`, `city_url`, `home_url`, `start`, `end`, and
`films` (each with `title`, `url`, `poster`, `year`, `description`, `genres`,
`genre_links` as `{name, url}` records, `directors`, `runtime`, and `age_rating`). Python supplies
JSON data to PostHog's capture-event action, never generated HTML. Do not move this data
into workflow variables: they have a 5KB limit, and batch overrides did not propagate
to invocations in production. A complete edition is substantially larger.
The template loops over films with Liquid and uses `{{ unsubscribe_url }}`.
Unsubscribe applies to all city editions in the newsletter's marketing category.
A signup does not override an existing unsubscribe or suppression.

Set these GitHub repository settings:

| Setting | Kind | Value |
| --- | --- | --- |
| `POSTHOG_PERSONAL_API_KEY` | Secret | Project-scoped key with Query Read, Hog flow Write (includes reads), and Person Read; single-email tests also need Group Read |
| `POSTHOG_PROJECT_ID` | Variable | EU PostHog project ID |
| `POSTHOG_NEWSLETTER_WORKFLOW` | Variable | `01a1408b-a71f-0000-c69b-722f68f522a8` (active shared delivery workflow) |
| `POSTHOG_NEWSLETTER_TEST_WORKFLOW` | Variable | `01a13a74-a5ed-0000-1426-d10c4299af81` (manual test workflow) |
| `NEWSLETTER_ENABLED` | Variable | `true` only after reviewing previews and testing the PostHog sender |

Manual workflow runs default to **data preview only** and upload JSON artifacts.
Render the email in PostHog using a mocked workflow test with that JSON under
`globals.event.properties.newsletter`; keep `mock_async_functions=true`. A local preview
uses PostHog credentials to discover cities, but does not send:

```sh
uv run newsletter --date 2026-10-15 --output /tmp/newsletter-preview
```

To test the normal delivery path, register a confirmed subscriber in PostHog and
manually run `Newsletter` with `send=true`. This discovers cities and sends to
the real audiences, not just one test address. Review the audience first.

For a **real single-recipient test**, manually run `Newsletter test email` in GitHub
Actions with the required `email` and `city` inputs. City matching ignores case,
including Swedish letters. It has no schedule and does not depend on `NEWSLETTER_ENABLED`.
The equivalent local command is `uv run newsletter --test-email ADDRESS --city Göteborg`.
It needs the API key, project ID and test workflow ID above, but no shared batch workflow.

Tests use the upcoming Thursday's edition (today if Thursday), and may run any day.
Incomplete history can produce an incorrect “new this week” selection.
An empty selection fails without sending. Test delivery does not subscribe the recipient.
Each test clones the manual PostHog workflow as a draft to snapshot the latest library
template, then invokes only its email step with the `email` variable and newsletter event data.
This checks rendering/delivery only; use the normal `Newsletter` job to test audience dispatch
and the event handoff end to end.
It never enables a workflow or creates a batch. The email step must use
`{{ variables.email }}`, no CC/BCC, and the marketing message type. Opt-outs still apply.
Failures and skipped sends fail the job; an uncertain response is not retried. Inspect
PostHog before rerunning, since a manual rerun sends another email.

An edition includes films screening next Friday through Thursday, excluding any
with a screening in that city during the 30 days before the edition's Friday
(including send day). The 30-day boundary is inclusive; older screenings do not
exclude a film. Identity uses normalized scraped titles across cinemas; differently
named editions/translations may still appear separately. Emails show posters,
titles, descriptions, directors, genres, runtime, age ratings and release years
when available, newest year first then Swedish alphabetical order;
unknown years come last. Original release years from movie metadata take priority
over cinema release dates, which can refer to re-releases. Cinema posters are
preferred, with TMDB posters as fallback. Metadata never decides which films qualify.
Poster and title links open the movie's anchor on the city page; the footer links
to the city programme. Genres link to the city's genre programme. Site links carry
`utm_source=allabiografer.se`, `utm_medium=email`, `utm_campaign=weekly-YYYY-MM-DD`
(the edition's Friday), and `utm_content=home|city|movie|genre`. Movie fragments
remain after the query string; no recipient data is added. Unsubscribe links and
poster image sources are not UTM-tagged.
The PostHog design uses the website's Fira Sans font, colours, compact movie rows,
and automatic `prefers-color-scheme` dark mode. Web fonts and dark-mode CSS depend
on the email client; inline light styles and system-font fallbacks remain usable.
Anchors cover canonical and scraped title aliases, once per
film even with multiple presentation variants. Emails contain no individual
screening dates, cinemas, or ticket links. Empty editions skip.

GitHub owns scheduling: one Thursday 09:00 cron with `timezone: Europe/Stockholm`.
There are no runtime weekday, clock, or retained-history gates. Manual runs use
the same path on any day and select the upcoming Thursday's edition. Incomplete
scraping history can make continuing films appear new, especially during the
first week. The script does not claim source completeness.

Every city/week creates two PostHog batch workflows, named
`allabiografer:<city>:<Friday date>`. Sending frequency relies on the GitHub schedule,
not an existing-edition check: repeated runs create more workflows and batches
for the same edition, with delivery deduplicated for seven days. Inspect that edition's batch jobs in PostHog before manually
recovering a failed run, especially after an uncertain API response. GitHub
serializes runs; do not run concurrent local senders. API writes are not automatically retried.
The job reports a queued batch, not confirmed delivery; inspect delivery in PostHog.
