# Newsletter

Start with the [state model](#state-model-and-transitions) and
[workflow lifecycle](#weekly-run-and-workflow-lifecycle). Operational details cover
[unsubscribe synchronization](#unsubscribe-synchronization-and-delivery-consent),
[the backend API](#backend-api-credentials-and-concurrency),
[configuration and testing](#github-configuration-and-operating-modes), and
[troubleshooting](#verification-and-troubleshooting).

## Architecture and ownership

The `Newsletter` GitHub Actions job prepares city editions on Thursdays at
09:00 Europe/Stockholm (GitHub may start scheduled jobs late). Python compares
upcoming screenings against 30 days of history, supplies structured movie data,
and starts city batches. The PostHog library template owns the subject, HTML,
plain text, and all wording. Edition audiences stay in PostHog. Unsubscribe
reconciliation reads opted-out addresses into runner memory only, not logs or artifacts.

The newsletter has three separate execution environments:

| Component | Owns | Does not own |
| --- | --- | --- |
| Website on Fly: static pages/JavaScript plus nginx/Lua | Signup, signed preferences links, subscription changes, native opt-out reconciliation | Scheduling, email rendering or sending |
| GitHub Actions and Python | Schedule, film selection, edition data, creating/dispatching batches, archival | A subscriber database or email HTML |
| PostHog | Person profiles, audience evaluation, persistent delivery workflows, library templates, sending, native marketing opt-outs and suppression | The meaning of our city subscriptions |

`newsletter_cities` on the PostHog person is our **only subscription authority**.
PostHog's native marketing opt-out and suppression are additional delivery gates,
not another list of subscribed cities. Being in a city audience does not guarantee
an email: membership, deduplication and delivery protections must all allow it.

The main paths are:

```text
City-page signup
  -> nginx/Lua -> PostHog person.newsletter_cities

Thursday GitHub run
  -> reconcile native unsubscribes -> archive completed idle batches
  -> discover subscribed cities -> select new films
  -> edition batch -> city-specific event -> persistent city workflow -> email

Email body preferences link
  -> our static preferences page -> nginx/Lua -> update newsletter_cities

Email-client unsubscribe button
  -> PostHog native opt-out -> unsubscribe event -> HTTP webhook destination
  -> nginx/Lua -> recheck current opt-out -> clear newsletter_cities
```

## State model and transitions

| State | Location | Meaning |
| --- | --- | --- |
| `email` | PostHog person | Normalized recipient address; lookup rejects ambiguous matching profiles |
| `newsletter_cities` | PostHog person | Sorted unique active city names, for example `["Göteborg", "Malmö"]`; `[]` means no subscriptions |
| `newsletter_preferences_token` | PostHog person | Signed, person-scoped bearer credential; not a subscription or confirmation flag |
| Native global marketing opt-out | PostHog messaging preferences, keyed by email | Blocks marketing delivery; synchronized into an empty city list |
| Bounce/complaint suppression | PostHog delivery system | Independent delivery protection; signup never clears it |
| `delivery_blocked` | Preferences API response only | Derived native global opt-out state; not a stored property or a report of all suppression reasons |
| Signup-row dismissal/success | Browser `localStorage` | Hides that city's signup prompt; not proof of a current subscription |
| Locks and pending writes | nginx shared memory | Temporary coordination within one backend instance; not durable subscription storage |

City membership is represented only by the array. Native messaging preferences
provide a global delivery opt-out, not per-city subscription state.

| Action | City-list transition | Native global opt-out |
| --- | --- | --- |
| Signup, currently opted in | Add the requested city; preserve other cities; no duplicates | Unchanged |
| Signup after native global opt-out | Replace the list with only the requested city | Clear only after the new list is visible; verify before returning success |
| Remove one city on our page | Remove that city; other cities remain | Unchanged |
| Unsubscribe all on our page | Set `[]` | Unchanged; the empty list excludes the person from city audiences |
| Email-client/native global unsubscribe | Eventually set `[]` through webhook or reconciliation | Set by PostHog before our notification |
| Delayed/repeated native callback after successful re-signup | No change: backend rechecks that the native opt-out is no longer active | Unchanged |

The preferences page shows only current memberships. Once a city is removed, it
disappears. Rejoining is an explicit city-page signup.

## Signup and recipient identity

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

For a new address, the backend first creates a newsletter identity, waits for
PostHog to assign a person UUID, then signs that UUID and writes the subscription.
Existing people are resolved by email and updated through their existing distinct
ID. The anonymous analytics browser identity is not used for signup. Signup is
single opt-in: there is no confirmation email or confirmation-state transition.
It does not create a delivery workflow or immediately send an edition.

## Weekly run and workflow lifecycle

Python discovers cities from `newsletter_cities` among people with a nonempty email.
City values must
match scraped city names exactly; unknown cities fail before any batches start.
New subscribed cities need no GitHub configuration or separate template workflow.

The real `--send` execution order is:

1. Reconcile native global opt-outs through the backend.
2. Archive eligible completed, idle edition dispatchers.
3. Query subscribed cities and validate every city against the screenings database.
4. For each city, prepare and save its JSON edition. Skip an empty edition.
5. Validate the shared blueprint; find/create and validate the city's persistent
   delivery workflow. A newly subscribed city gets its workflow here, on its first
   nonempty send, not during signup.
6. Create an active edition dispatcher and start its batch job. PostHog evaluates
   the audience and captures a city event per matching person.
7. The persistent city workflow rechecks membership, deduplicates the edition,
   and sends the marketing email subject to native delivery protections.
8. A later real newsletter run archives the dispatcher once the archival checks pass.

This is not one transaction across all cities. If a later city fails, earlier
batches may already be queued. A queued batch is not a delivery receipt.

| PostHog object | Shape and purpose | Lifecycle |
| --- | --- | --- |
| Shared delivery blueprint | Generic event → native email → exit; configuration source for city workflows | Active and unscheduled; normal dispatch uses city-specific events, not its generic event |
| `allabiografer:delivery:<city>` | City event → native email → exit; actual sending and edition deduplication | Created as a draft, activated before first dispatch, then reused across editions; not automatically archived |
| `allabiografer:<city>:<Friday date>` | Batch audience → capture city event → exit; dispatches edition data, not email | New active workflow/batch on each nonempty city send; archived later only when completed and idle |
| Manual test blueprint | Manual trigger → native email → exit; recipient supplied by `variables.email` | Reusable draft; never enabled by the test sender |
| `allabiografer:test:<city>:<UUID>` | Snapshot of the latest library template for one real email-step invocation | Created as a draft; no batch and no activation; inspect and archive manually after testing |
| Native unsubscribe destination | Filtered event → authenticated HTTP POST to our backend | Long-lived enabled event destination; not an email workflow or edition batch |

The word “function” in PostHog's API (`hog_function`) also covers event destinations.
Our unsubscribe function is only a webhook bridge; it does not replace the email
workflows. Edition dispatchers separately use a capture-event function as a step.

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

### Automatic archival

At the start of each `--send` run, Python archives previous edition batch dispatchers
only when all their batch jobs are completed, no running/failed/canceled runs are
reported since workflow creation, and PostHog confirms there are no in-flight runs.
Scheduled workflows and workflows with unpublished drafts are left alone. Unknown
in-flight counts defer cleanup; API errors stop the run before dispatch. Preview
and single-recipient test runs never archive workflows. Persistent city delivery
workflows and the shared blueprint remain active between editions.

Only active workflows named exactly `allabiografer:<city>:<YYYY-MM-DD>` with one
batch trigger are candidates, and they must have at least one batch job. Archival
is a status change, not deletion. An idle batch with any recorded failed or canceled
run is retained for investigation, even if its batch job says completed.
Dispatcher completion describes event dispatch; it does not prove that every
separate city delivery invocation has delivered an email.

### Audience membership and duplicate protection

Both the blueprint and city workflows must deduplicate
`{person.id}:{event.properties.newsletter.city}:{event.properties.newsletter.start}`
for at least seven days, without a threshold. This prevents repeat delivery while
allowing one edition for each subscribed city.

Batch and event filters use different representations of person properties:

```text
Batch: has(JSONExtract(ifNull(properties.newsletter_cities, '[]'), 'Array(String)'), 'Göteborg')
Event: has(person.properties.newsletter_cities, 'Göteborg')
```

Do not replace these with an `exact` city-string comparison: the property is an
array, and equality is not membership. The second check prevents an already
dispatched event from sending after the person leaves that city's audience,
subject to asynchronous person updates. Deduplication is not permanent edition
idempotency: rerunning an old edition after its masking TTL can send it again.

## Email template and preferences page

Select a verified sender and **marketing** message type on the blueprint, without
a named category: native global unsubscribe preferences apply to every city.
The recipient is `{{ person.properties.email }}`, without CC/BCC. Optional audience filters and
email sending rate limits belong on the blueprint and city workflows. Select the library template
`01a138fb-15dd-0000-72dc-6b0dc068ba35` on the email action (`config.template_uuid`).
Template-library edits do not automatically update workflow snapshots:
update and publish the blueprint and existing city email actions in PostHog after
changing the library template. New city workflows copy the blueprint at first use.
The template reads `event.properties.newsletter`: `city`, `city_url`, `home_url`, `start`, `end`, and
`films` (each with `title`, `url`, `poster`, `year`, `description`, `genres`,
`genre_links` as `{name, url}` records, `directors`, `runtime`, and `age_rating`). Python supplies
JSON data to PostHog's capture-event action, never generated HTML. Edition data lives
in event properties, not workflow variables, whose 5KB limit is smaller than a
complete edition.
The template loops over films with Liquid. Its visible HTML and plain-text preferences
link must be `https://allabiografer.se/nyhetsbrev/installningar/#token={{ person.properties.newsletter_preferences_token }}`,
not `{{ unsubscribe_url }}`. The static private page calls `/api/newsletter/preferences`
using the signed token in an Authorization header. It lists only active subscriptions,
and offers one-city removal and unsubscribe-all. Rejoining uses the city-page signup form.
It has no analytics, referrers or persistent token storage. The URL fragment is removed
immediately. Refreshing requires reopening the original email link.

## Unsubscribe synchronization and delivery consent

PostHog sends marketing emails and enforces native email-client unsubscribe
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

The visible body link and the email client's unsubscribe button are different
paths. We control the body link. PostHog generates the `List-Unsubscribe` and
`List-Unsubscribe-Post` headers; changing our HTML link does not change them.
Do not classify newsletters as transactional to avoid these headers or native
marketing opt-outs. Native preference changes are email-scoped, while our tokens
and city arrays belong to a person UUID.

### Native unsubscribe destination configuration

The backend must be available while the destination and newsletter sender are active.
Native `List-Unsubscribe` headers and marketing classification remain enabled.

In EU project `273892`, the production destination is
`Newsletter native unsubscribe sync` (`01a18b97-6c0f-0000-d4b4-57c65779f37f`).
The destination and engagement-event capture are enabled. Inspect the existing
destination before changing it or creating another one.

1. `capture_workflows_engagement_events` is enabled through PostHog's
   `/api/projects/{project_id}/workflow_sending_rules/current/` endpoint. These
   engagement events count toward PostHog event usage.
2. The HTTP Webhook destination (`template-webhook`) is filtered to
   `$workflows_email_unsubscribed` with event property `category` exactly `$all`.
   It POSTs JSON to `https://allabiografer.se/api/newsletter/native-unsubscribe` with
   `email` set from the event's `$email` property, not the resolved person's ID.
3. `Content-Type` is `application/json`. `Authorization: Bearer <token>` is stored
   in the destination's encrypted `secret_headers`, not ordinary headers.
   The token is lowercase hex HMAC-SHA256 using `NEWSLETTER_SIGNING_SECRET`
   over the exact UTF-8 string `newsletter-preferences:v1:native-unsubscribe`.
   Never print it or put it in a URL. The webhook template throws on HTTP status
   400 or higher so failed calls are reported as failures.

Our preferences-page actions write only `newsletter_cities`; they do not create
native city categories or a second subscription flag. `delivery_blocked` in the API
response is derived from the current native global opt-out, not a stored person property.

## Backend API, credentials and concurrency

All three endpoints require POST with `Content-Type: application/json`. The
backend rejects a supplied foreign `Origin`; there is no cross-origin browser API.

| Endpoint | Authorization | JSON request | Successful response/effect |
| --- | --- | --- | --- |
| `/api/newsletter/signup` | Public, IP-rate-limited | `{ "email": "reader@example.org", "city": "Göteborg" }` | `{ "success": true }`; no profile details or token returned |
| `/api/newsletter/preferences` | `Authorization: Bearer <person token>` | `{}` | `{ "cities": ["Göteborg"], "delivery_blocked": false }`; also reconciles an outstanding native opt-out |
| Same preferences endpoint | Same person token | `{ "city": "Göteborg", "unsubscribe": true }` | Updated city list; removing a city that is not subscribed returns 400 |
| Same preferences endpoint | Same person token | `{ "unsubscribe": true }` | Empty city list |
| `/api/newsletter/native-unsubscribe` | Separate server-to-server bearer credential | `{ "email": "reader@example.org" }` | `{ "success": true }`; clears cities only for an existing, currently natively opted-out profile |

The browser reloads canonical preferences after a successful removal and disables
controls while a request is in flight. A failed/uncertain save offers a read retry,
not an automatic repeat of the mutation. The backend does not expose upstream
errors or whether an unknown callback recipient exists. Invalid credentials return
401, conflicting profiles can return 409, rate limiting returns 429, and
upstream failures or unconfirmed writes return 502/503. A timeout is not proof
that the write failed; inspect current state before repeating it.

The Alpine image installs nginx's Lua/NDK modules plus cjson, resty HTTP, lock,
OpenSSL and string libraries. Runtime environment needs `POSTHOG_PROJECT_ID`,
`POSTHOG_PROJECT_TOKEN`, `POSTHOG_PERSONAL_API_KEY` (Person Read and Hog flow Read/Write),
and `NEWSLETTER_SIGNING_SECRET` (at least 32 random ASCII characters). Keep the
secret stable so issued links remain valid.
Provision secrets through the existing deployment secret mechanism, never build args.
The public project token may be provided at build time; it is retained for runtime.
`POSTHOG_API_HOST` defaults to EU Cloud; `POSTHOG_CAPTURE_HOST` defaults to EU ingestion.
HTTP loopback overrides and `NEWSLETTER_CITIES_FILE` are used only in local tests.

Person links have the format `UUID.hex_signature`, where the signature is
HMAC-SHA256 over `newsletter-preferences:v1:<UUID>`. The backend verifies both
the signature and equality with the token stored on that person. Signup regenerates
the same token for the same UUID/secret. These tokens have no built-in expiry;
replacing the signing secret invalidates all links and also requires updating
the unsubscribe destination's separately scoped credential. Never expose the
personal API key or signing secret in static assets, build arguments, links or logs.
Tokens contain no email address. They are long-lived bearer credentials:
forwarding a link grants access to that recipient's newsletter preferences.
Replacing the stored token revokes its link; signup regenerates the deterministic
token described above. Merging or deleting the person can also invalidate links.

Run **one backend instance**. Lua locks serialize each email's array updates within
that instance, including signup versus unsubscribe; multi-instance writes require a
shared lock/store before scaling.
PostHog profile writes use ingestion and are asynchronous. While holding the lock,
the backend waits for read-back and records pending writes in shared memory so
later requests cannot overtake or blindly resend an uncertain write. Shared memory
does not survive a machine restart; inspect outstanding state after recovery.
The static `mise run serve` preview does not run Lua. API tests run real Lua-enabled
nginx in the Nix shell against a local PostHog HTTP fixture.

## GitHub configuration and operating modes

Set these GitHub repository settings:

| Setting | Kind | Value |
| --- | --- | --- |
| `POSTHOG_PERSONAL_API_KEY` | Secret | Project-scoped key with Query Read, Hog flow Write (includes reads), and Person Read; single-email tests also need Group Read |
| `POSTHOG_PROJECT_ID` | Variable | EU PostHog project ID |
| `POSTHOG_NEWSLETTER_WORKFLOW` | Variable | `01a1408b-a71f-0000-c69b-722f68f522a8` (active shared delivery workflow) |
| `POSTHOG_NEWSLETTER_TEST_WORKFLOW` | Variable | `01a13a74-a5ed-0000-1426-d10c4299af81` (manual test workflow) |
| `NEWSLETTER_ENABLED` | Variable | `true` only after reviewing previews and testing the PostHog sender |

Managing the unsubscribe destination additionally needs `hog_function:read` and
`hog_function:write`; these are not required by the normal weekly sender. Enabling
engagement-event capture requires project-admin access. Keep credentials in the
existing GitHub/Fly secret stores; permission changes do not require replacing the key.

Manual workflow runs default to **data preview only** and upload JSON artifacts.
Render the email in PostHog using a mocked workflow test with that JSON under
`globals.event.properties.newsletter`; keep `mock_async_functions=true`. A local preview
uses PostHog credentials to discover cities, but does not send:

```sh
uv run newsletter --output /tmp/newsletter-preview
```

To test the normal delivery path, register a subscriber through the city-page form and
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

## Edition selection and presentation

An edition includes films screening next Friday through Thursday, excluding any
with a screening in that city during the 30 days before the edition's Friday
(including send day). The 30-day boundary is inclusive; older screenings do not
exclude a film. Identity uses normalized scraped titles across cinemas; differently
named editions/translations may still appear separately. Emails show posters,
titles, descriptions, directors, genres, runtime, age ratings and release years
when available. Films are ordered first by the number of screenings in the edition, descending,
then by newest release year and Swedish alphabetical title. Unknown years sort
after known years when screening counts tie. Original release years from movie metadata take priority
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

## Verification and troubleshooting

- **Signup fails:** inspect city allowlist freshness, duplicate email profiles,
  API-key permissions, pending asynchronous writes and native opt-in restoration.
  Local signup-row hiding is not the source of subscription truth.
- **Cities present but no email:** check the edition has films, batch enrollment,
  capture-event success, the city's event-triggered workflow, seven-day deduplication,
  native opt-outs, suppression, pauses, and sending limits. Do not clear suppression
  or mark mail transactional as a workaround.
- **Native opt-out and city list disagree:** check engagement-event capture and
  the enabled destination's filter, encrypted authorization and execution logs.
  Read PostHog directly when diagnosing: opening our preferences page can itself
  repair the list and hide whether the webhook worked.
- **An old batch remains active:** inspect every archival condition, especially
  failed/canceled runs, drafts, schedules and unknown/in-flight counts. Do not force
  archive a workflow simply because its batch job completed.
- **Template changes are missing:** library edits do not propagate to existing
  blueprint/city snapshots. Update, test and publish those snapshots separately.
- **An uncertain send or failed run:** inspect existing edition workflows, batch
  jobs and delivery logs before retrying. Earlier cities may already have sent.

For an authorized live acceptance test: record the recipient's initial city list
and native preference; use the public form to subscribe to two cities; open the
actual received body link and remove one city, then all; rejoin; invoke the received
native one-click header; verify the native opt-out and eventual empty list directly
without triggering fallback reconciliation; rejoin one city; replay a delayed
callback and confirm the city remains. Confirm actual mailbox delivery rather than
only a successful test invocation. Restore the original subscription only when
authorized, and archive disposable test drafts after inspection. Never broadcast
to real audiences just to test one recipient.

Implementation references:

- [Edition generation, audiences, delivery and archival](../src/newsletter/__init__.py)
- [Signup, tokens, preferences, native synchronization and locks](../etc/nginx/lua/newsletter.lua)
- [Backend routes and rate limiting](../etc/nginx/sites-available/allabiografer.se)
- [Signup browser behavior](../static/i/newsletter.js) and [private preferences behavior](../static/i/newsletter-preferences.js)
- [Weekly scheduler](../.github/workflows/newsletter.yml) and [single-email test job](../.github/workflows/newsletter-test.yml)
