# allabiografer.se

A static site aggregating cinema screenings across Sweden. Reimplementation of [allekinos.de](https://allekinos.de/) by [Nikita Tonsky](https://tonsky.me/) for the Sweden.

## Development (Nix on Linux)

Enter the pinned development shell (Nix with flakes enabled):

```sh
nix develop
git lfs install --local
git lfs pull origin
uv sync --locked --group dev --group parse --group build
```

The shell supplies uv, Git LFS, mise, Node, Chromium, fallback fonts, and the
C++ runtime needed by Python wheels such as greenlet and curl_cffi. Python
dependencies and tasks remain managed by `pyproject.toml`, `uv.lock`, and
`mise.toml`; Nix does not install Python packages. The database, posters, and
web fonts use Git LFS: hydrate them before building or testing, rather than
using the small pointer files from an unhydrated checkout.

Before using `mise run` in a new checkout, review `mise.toml` and run
`mise trust` if mise reports that the configuration is not trusted.

Run tests inside the shell:

```sh
uv run --locked --group dev --group parse --group build pytest
node --test tests/*.test.cjs
```

Browser tests use the shell's `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` and font
configuration; no `playwright install` or browser download is needed. Outside
Nix, tests retain Playwright's default browser lookup (or accept the same
environment variable for an existing Chromium). The Nix shell currently
supports x86_64 and aarch64 Linux.

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
Edition audiences stay in PostHog. Unsubscribe reconciliation reads opted-out
addresses into runner memory only; addresses and tokens are never logged or committed.

The city-page form uses single opt-in: JavaScript POSTs `{email, city}` to
`/api/newsletter/signup`. Nginx's Lua module validates the city against the generated
`/i/newsletter-cities.json`, normalizes the email, and adds it to the person's
`newsletter_cities` array in PostHog. This array is the only subscription state:
removing a city unsubscribes it; an empty array means unsubscribed from everything.
There is no receive boolean, separate confirmation flag, or disabled-city history.
Signup does not attach the email to the anonymous analytics identity or disclose
a person's preferences token to the browser. Explicit signup after a native global
opt-out starts with only the requested city, waits for that list to be visible, then
restores native marketing consent. It never restores previously opted-out cities
or changes bounce/complaint suppression or tracking consent. Failure to restore
marketing consent fails the signup request rather than claiming success.
The form links to `/nyhetsbrev/` for subscription and privacy information.

Python discovers cities from `newsletter_cities` among people with a nonempty email.
City values must
match scraped city names exactly; unknown cities fail before any batches start.
New subscribed cities need no GitHub configuration or separate template workflow.

Use one **active**, unscheduled PostHog delivery blueprint: event trigger → one native
email → exit. It listens for `newsletter_edition_ready` and its ID is
`01a1408b-a71f-0000-c69b-722f68f522a8`.
Do not restrict the city in this blueprint: Python creates one batch dispatcher with its audience filters
and membership in `newsletter_cities`. It captures one event per matching
person with the edition in `event.properties.newsletter`.

Before dispatch, Python finds or creates a persistent `allabiografer:delivery:<city>`
workflow without a named marketing category. The city workflow
copies the blueprint's sender, email snapshot, audience filters, rate limit and deduplication.
It also checks city membership, and listens only for `newsletter_edition_ready:<city>`; the generic blueprint cannot
also send that event. Existing city workflows are reused, not recreated for each edition.
Paused or misconfigured city workflows fail before any batch for that city is dispatched.
Recipient addresses stay in PostHog.
At the start of each `--send` run, Python archives previous edition batch dispatchers
only when all their batch jobs are completed, no running/failed/canceled runs are
reported since workflow creation, and PostHog confirms there are no in-flight runs.
Scheduled workflows and workflows with unpublished drafts are left alone. Unknown
in-flight counts defer cleanup; API errors stop the run before dispatch. Preview
and single-recipient test runs never archive workflows. Persistent city delivery
workflows and the shared blueprint remain active between editions.
Both the blueprint and city workflows must deduplicate
`{person.id}:{event.properties.newsletter.city}:{event.properties.newsletter.start}`
for at least seven days, without a threshold. This prevents repeat delivery while
allowing one edition for each subscribed city.

Select a verified sender and **marketing** message type on the blueprint, without
a named category: legacy unsubscribe preferences are global and continue to apply
to every city. If migrating a blueprint with a named category, preserve its existing
opt-outs before changing categories; the sender refuses to do that migration implicitly.
Leave the recipient
as `{{ person.properties.email }}`, without CC/BCC. Optional audience filters and
email sending rate limits belong on the blueprint and city workflows. Select the library template
`01a138fb-15dd-0000-72dc-6b0dc068ba35` on the email action (`config.template_uuid`).
Template-library edits do not automatically update workflow snapshots:
update and publish the blueprint and existing city email actions in PostHog after
changing the library template. New city workflows copy the blueprint at first use.
The template reads `event.properties.newsletter`: `city`, `city_url`, `home_url`, `start`, `end`, and
`films` (each with `title`, `url`, `poster`, `year`, `description`, `genres`,
`genre_links` as `{name, url}` records, `directors`, `runtime`, and `age_rating`). Python supplies
JSON data to PostHog's capture-event action, never generated HTML. Do not move this data
into workflow variables: they have a 5KB limit, and batch overrides did not propagate
to invocations in production. A complete edition is substantially larger.
The template loops over films with Liquid. Its visible HTML and plain-text preferences
link must be `https://allabiografer.se/nyhetsbrev/installningar/#token={{ person.properties.newsletter_preferences_token }}`,
not `{{ unsubscribe_url }}`. The static private page calls `/api/newsletter/preferences`
using the signed token in an Authorization header. It lists only active subscriptions,
and offers one-city removal and unsubscribe-all. Rejoining uses the city-page signup form.
It has no analytics, referrers or persistent token storage. The URL fragment is removed
immediately. Refreshing requires reopening the original email link.

PostHog still sends marketing emails and enforces native email-client unsubscribe
and bounce suppression; these protections are never bypassed by marking mail transactional.
A native global unsubscribe clears `newsletter_cities` through an authenticated
webhook. The backend resolves the existing person by email, not the native event's
distinct ID, and checks the current global opt-out while holding the signup lock.
Duplicate notifications do nothing; delayed notifications cannot undo a later signup
whose native marketing consent has been restored. Unknown recipients create no profiles.

Notifications are best-effort. Opening our preferences page also reconciles a native
opt-out, and every real `--send` run reconciles opted-out subscribers before discovering
cities, archiving batches, or dispatching editions. That fallback uses the same locked
backend and person-scoped token, never forwards the project API key to our site, and
stops the run on failed or ambiguous reconciliation. Preview/test-email runs do not
perform this project-wide cleanup. Until reconciliation finishes, PostHog's native
delivery block remains in place. This is eventual consistency, not an atomic change
across PostHog and our list. Native opt-outs may take roughly 5–6 minutes to affect delivery.
Person updates are asynchronous too: the API waits for read-back before claiming success,
retains uncertain writes in shared memory, and does not automatically resend them.

### Native unsubscribe notification setup

Deploy the backend before enabling the destination or running the updated sender.
Keep existing native `List-Unsubscribe` headers and marketing classification intact.

1. Enable `capture_workflows_engagement_events` through PostHog's
   `/api/projects/{project_id}/workflow_sending_rules/current/` endpoint. These
   engagement events count toward PostHog event usage.
2. Configure an HTTP Webhook destination (`template-webhook`), filtered to
   `$workflows_email_unsubscribed` with event property `category` exactly `$all`.
   POST JSON to `https://allabiografer.se/api/newsletter/native-unsubscribe` with
   `email` set from the event's `$email` property. Do not use the resolved person's ID.
3. Set `Content-Type: application/json`, and put `Authorization: Bearer <token>`
   in the destination's encrypted `secret_headers`, not ordinary headers.
   Derive the token as lowercase hex HMAC-SHA256 using `NEWSLETTER_SIGNING_SECRET`
   over the exact UTF-8 string `newsletter-preferences:v1:native-unsubscribe`.
   Pass it directly to the encrypted input; never print it or put it in a URL.
   The destination must treat non-2xx responses as failures so retryable errors retry.
4. Publish/enable the destination and verify native unsubscribe, re-signup, and a
   delayed callback using an authorized test recipient. Verify both the city array
   and native global preference; do not remove bounce or complaint suppression.

Our preferences-page actions write only `newsletter_cities`; they do not create
native city categories or a second subscription flag. `delivery_blocked` in the API
response is derived from the current native global opt-out, not a stored person property.

### Preferences backend and migration

The Alpine image installs nginx's Lua/NDK modules plus cjson, resty HTTP, lock,
OpenSSL and string libraries. Runtime environment needs `POSTHOG_PROJECT_ID`,
`POSTHOG_PROJECT_TOKEN`, `POSTHOG_PERSONAL_API_KEY` (Person Read and Hog flow Read/Write),
and `NEWSLETTER_SIGNING_SECRET` (at least 32 random ASCII characters). The secret
must be the same for the migration and app; keep it stable so old links work.
Provision secrets through the existing deployment secret mechanism, never build args.
The public project token may be provided at build time; it is retained for runtime.
`POSTHOG_API_HOST` defaults to EU Cloud; `POSTHOG_CAPTURE_HOST` defaults to EU ingestion.
HTTP loopback overrides and `NEWSLETTER_CITIES_FILE` are used only in local tests.

Run **one backend instance**. Lua locks serialize each email's array updates within
that instance, including signup versus unsubscribe; multi-instance writes require a
shared lock/store before scaling. Do not run the migration concurrently with signups.
The static `mise run serve` preview does not run Lua. API tests run real Lua-enabled
nginx in the Nix shell against a local PostHog HTTP fixture.

Before deploying this version, pause newsletter dispatch and old signups, then:

1. Configure the runtime credentials and signing secret. The migration reuses the
   public project token for profile updates and needs Hog flow Write for cutover.
   Only optional legacy-field pruning needs Person Write. Do not emit secrets or tokens into logs.
2. Run `uv run python -m newsletter.migrate` for a read-only summary. It combines legacy
   city keys, removes native city opt-outs, and empties globally opted-out lists.
   Existing `newsletter_cities`, including `[]`, are authoritative on reruns.
3. After approval, run with `--apply --cutover`. It writes and verifies arrays
   and signed personal links, retains old keys for rollback, then removes named categories from
   existing city delivery workflows and adds membership filters. It never sends mail,
   clears native opt-outs, or changes suppression. Unknown named blueprint/test
   categories need explicit consent review; the sender refuses them.
4. Replace the visible library-template preferences links, then publish updated
   blueprint and city email snapshots in PostHog. Keep native List-Unsubscribe intact.
5. Deploy one app instance and validate with an explicitly authorized recipient before
   resuming the schedule. Prune legacy fields separately with `--apply --prune` only
   after verification; do not run old senders after pruning legacy properties.

Dry-run summaries contain counts, not addresses or tokens. Links use PostHog's person
UUID and HMAC-SHA256 scoped to newsletter preferences, with constant-time signature
comparison in Lua. Signup creates and reads back a new profile before signing its UUID.
Backfill replaces old tokens and removes `newsletter_preferences_id`; old links stop working.
Tokens never contain email addresses. They are long-lived
bearer credentials: forwarding a link grants access to that recipient's newsletter
preferences only. Replacing a person's stored token revokes the old link. Merging or
deleting that PostHog person can also invalidate its links.

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
template, keeps marketing type without a named category, then invokes only its email step
with the `email` variable and newsletter event data.
This checks rendering/delivery only; use the normal `Newsletter` job to test audience dispatch
and the event handoff end to end.
An immediate test after changing opt-outs may still use cached preferences.
To validate consent enforcement, allow at least six minutes after the last preference
change and use normal city events for an explicitly authorized test recipient,
never a broadcast to the subscriber audience.
It never enables a workflow or creates a batch. The email step must use
`{{ variables.email }}`, no CC/BCC, and the marketing message type.
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

Every city/week creates one PostHog batch workflow, named
`allabiografer:<city>:<Friday date>`. Sending frequency relies on the GitHub schedule,
not an existing-edition check: repeated runs create more workflows and batches
for the same edition, with delivery deduplicated for seven days. Inspect that edition's batch jobs in PostHog before manually
recovering a failed run, especially after an uncertain API response. GitHub
serializes runs; do not run concurrent local senders. API writes are not automatically retried.
The job reports a queued batch, not confirmed delivery; inspect delivery in PostHog.
