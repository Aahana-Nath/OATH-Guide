# Verification: what was checked, what changed, what remains uncertain

The question this answers: **can a developer trust these guides?** The short version: every quote is real and traceable, most
numbers match the provider's current docs, and checking a sample against independent sources found real mistakes. Those are
fixed or flagged below. A guide is still research, not a substitute for trying the setup.

## How it was checked

| Layer | What it proves | What it cannot prove |
|---|---|---|
| **1. Quote check at generation time** (in the agent) | Every documentation claim carries a quote copied exactly from the fetched page. Invented quotes are dropped and listed. | That the quote is *relevant* or *complete*. |
| **2. Independent re-check** ([`tools/recheck_quotes.py`](../tools/recheck_quotes.py)) | Re-fetches every cited URL from scratch and confirms the quote is still there. | Same as layer 1. |
| **3. Manual cross-check against pages the agent did not cite** | That the *content* is right: numbers, gates, waits. Sources fetched independently. | Anything behind a login. |
| **4. Reproduction of the agent's live "Tested" claims with `curl`** | That observations such as "redirects to sign-in" are real and repeatable. | Whether they generalise. |
| **5. Comparison with the human-tested guides** ([GitHub](../guides/github.json), [Slack](../guides/slack.json)) | Where the agent agrees with, or misses, what a person found by actually registering. | n/a |
| **6. Test-then-save gate** (in the agent, [`savecheck.py`](../agent/savecheck.py)) | Before a guide is saved, every cited page is fetched again (HTML and markdown renditions) and every quote re-checked. A claim that fails is removed, with anything that rested only on it, and the guide is re-validated. The result is recorded in the guide as a tested claim. | That a documentation claim is *true*, only that it is still on its source. |

Run layer 2 yourself: `python tools/recheck_quotes.py guides/*-agent.json`.

## Layer 2 result

**504 of 504 documentation quotes were re-found at their cited source** across all fourteen agent-researched guides (GitHub, Slack,
Spotify, Shopify, Notion, Google, Figma, Asana, Calendly, Dropbox, Linear, Zoom, Atlassian, Stripe). Zero were fabricated.

**Drift found by the re-check.** On the first re-check, three Notion quotes from `developers.notion.com/guides/get-started/overview` were no longer on the page: it had changed in the two days since the guide was saved. The guide was regenerated and its 38 quotes all re-found. Documentation guides go stale; the guide's "generated" date and the re-check tool (`tools/recheck_quotes.py`) are how a reader or a maintainer finds out.
Every guide also passed its own save-time gate (the "Tested before saving" card), with no claims removed.

**A caution about the checking tool itself.** An earlier pass reported 18 Shopify misses. They were not in the guide: shopify.dev
serves **different text for the same URL** depending on the request (an HTML rendition, which contains the quote, and a markdown
rendition, which does not), and the first version of the tool fetched each page once per quote, in bursts. The tool and the gate now
fetch each page once per rendition, by name, one request at a time per host. If you see unexplained misses on a docs site, suspect
the site's content negotiation before suspecting the guide.

## Layer 3 to 5: the sample

### Confirmed

| Claim in the guide | Checked against | Result |
|---|---|---|
| **Notion:** 600 requests/min per connection on Business and Enterprise, 180 on other plans; data-source queries about 3 requests/s | Notion's "Request limits" page, fetched live | ✅ Exact match. |
| **Calendly:** 500 requests/user/min (paid) and 50 (free); 8 OAuth tokens per user per minute; PKCE with `S256` is mandatory; production redirect URIs must be HTTPS; client secret is shown once | Calendly's "Rate limits" and "Creating an OAuth app" pages, fetched live | ✅ All match. This was the unfamiliar app run live in the UI. |
| **Google:** 100 test-user cap; hard cap of 100 users for unverified published apps | Google's "OAuth app state overview" table | ✅ Matches. A third-party summary from a web search said an unverified app in production has *no* cap; Google's own table says 100. The official page wins and the guide agrees with it. |
| **Slack:** preliminary review up to 10 business days, functional review up to 10 weeks for new apps | Slack's review guide (fresh fetch) and the human-tested Slack guide | ✅ Matches both. |
| **Spotify** rate limit is a rolling 30-second window | Spotify's rate-limit page | ✅ |
| **Notion** 5-10 business day review; **Asana** initial response within one week; **Google** brand verification 2-3 business days, sensitive-scope verification up to 10 days | Quotes re-found at the cited official pages | ✅ |
| **Live probes:** GitHub's authorize endpoint redirects an unauthenticated request to `github.com/login`; `/settings/applications/new` ends on a sign-in page; Slack's apps page says "You'll need to sign in to your Slack account to create an application"; Slack's `robots.txt` disallows `/oauth` (so the agent correctly skipped that endpoint) | Reproduced with `curl` | ✅ All four reproduce. |
| **New live tests:** GitHub's unauthenticated API sends `x-ratelimit-limit: 60`; Atlassian's API (after a redirect) sends `x-ratelimit-limit: 400, 400;w=60`; Calendly's API answers a no-token request with HTTP 401, and its token endpoint answers an invalid request with `invalid_client` (HTTP 401); Dropbox publishes `token_endpoint_auth_methods_supported` of `client_secret_post`, `client_secret_basic`, `none`, `private_key_jwt` and PKCE methods `plain`, `S256` | Reproduced with `curl` | ✅ All five reproduce exactly. |

### Corrected (mistakes found by checking, then fixed in the agent)

| What was wrong | How it was found | Fix |
|---|---|---|
| **Spotify's real gate was missing.** The first guide said extended quota needs "application and approval", rated going public "medium", and showed the approval wait as "Development Mode: default". Spotify's quota-modes page says development mode allows 5 users and needs the owner on Premium; extended quota is for **organizations only, with at least 250k monthly active users**, and review takes **up to six weeks**. | Fetched Spotify's quota-modes page and compared. The agent had never read that page. | Quota-related links now score higher. Re-run: public difficulty **hard**, wait **up to six weeks**, 250k users and organizations-only both present. Still missing: the 5-user development-mode cap. |
| **"Approval waits" that were not waits:** Spotify "Development Mode: default", Shopify "regularly / at their discretion / before it goes live", GitHub "not specified". | Reading the approval-wait line for every guide. | A review stage now only counts if its text states a duration. Otherwise the guide says "Not found". |
| **Unrelated product docs leaked in.** GitHub's steps included **seven steps for installing the Copilot IDE extension** plus "Copilot access: required"; Figma listed Code Connect requirements (Node 18, a Dev seat). Every quote was real, so the quote check could not catch it. | Comparing GitHub's agent guide with the human-tested one. | Requirements and steps must come from a page that is actually about OAuth or app registration. GitHub went from 15 steps to **8**, matching the human-tested path. |
| **A conditional requirement shown as required.** "Organization ownership: required", from "To offer paid plans for your app, the app must be owned by an organization". You can register under a personal account. | Reading the source quote. | Now "optional (only in some cases)". |
| **A false live-test claim (Atlassian).** The portal probe reported that a developer-docs page "ended on a sign-in page". The page had only redirected to add a trailing slash, and "Sign in" is in the site's navigation bar. | Reading the new guide's tested claims against the page with `curl`. | A redirect now counts only if it moves to a different path, with a regression test. Atlassian was regenerated, and the claim is gone. |
| **Duplicate limits** (Google listed "Test user cap" twice). | Reading the guide. | De-duplicated. |
| **Steps silently discarded.** Dropbox's and Linear's guides had **zero real setup steps** even though 10 and 4 steps had been extracted and verified. Steps were only kept from pages whose *URL* contained words like "quickstart", "creating" or "register" (a rule tuned on Slack and GitHub), so `/oauth` and `oauth-2-0-authentication` pages were thrown away. | Auditing why the library's thinnest guides were thin. | The rule now also accepts OAuth and authorization pages. Linear now has 5 steps starting at "Create a new OAuth2 application", Dropbox 5, and Atlassian went from 3 to 9. GitHub was re-run as a regression check and is unchanged (8 steps, no Copilot). |
| **Zoom's guide was empty** (no requirements, limits or blockers). Zoom's main docs site is JavaScript-rendered and its `robots.txt` blocks sub-pages, which the agent respects. | Reading the run log. | Researched from `developers.zoom.us` directly instead: 6 steps, 7 requirements, 29 verified claims. Recorded as a known limitation. |
| **A misleading live probe.** Figma's metadata described its *MCP server*, not the standard app OAuth flow, yet was reported as "OAuth server metadata… apps may be creatable through an API". | Reproducing the probe with `curl` and reading the scope (`mcp:connect`). | Every observation from MCP or OpenID metadata now carries a caveat, and the docs' authorize URL is preferred over it. |
| **A meaningless live probe.** Asana's marketing page "opened without signing in (HTTP 200)". | Reading the probe output. | A plain HTTP 200 is no longer reported as evidence; it is listed as "not completed". |
| **Outbound-request safety.** A public "type any URL" box could be used to make the agent fetch `file://` or internal addresses. | Threat review before packaging for hosting. | Added [`netguard.py`](../agent/netguard.py): http(s) only, public addresses only, redirects re-checked. Covered by [`tests/unit_test.py`](../tests/unit_test.py). |

### Could not verify

| Item | Why |
|---|---|
| **Difficulty ratings** (Easy / Medium / Hard) | Model judgement from the verified claims, so they are labelled *Inferred*. There is no ground truth to check them against. Spotify's rating changed from medium to hard once the missing facts were found, which shows how much they depend on coverage. |
| **"What an agent can do for you"** lists | Model suggestions, labelled *Inferred*. |
| **Time to get started** | "Unknown" in every agent guide. Only a hands-on attempt shows how long registration takes. |
| **Shopify's review duration** | Shopify's "Submit your app for review" page, fetched independently, states none. The guide says "Not found". |
| **Form fields and behaviour behind a login** | The human-tested GitHub guide found the required fields (app name, homepage URL) and that the client secret is shown once. The agent's GitHub guide has no form-level detail because it stops at the sign-in wall. |
| **Calendly going public** | The pages read do not cover a marketplace or review process, so "unknown". |
| **Run-to-run stability** | The agent is not deterministic. Two runs of the same app can list different limits or blockers. |

## What I learned

1. **Verifying that a quote exists is necessary but not sufficient.** The worst defects (Copilot steps in GitHub's guide, Spotify's missing gate) had perfectly genuine quotes. Catching them took comparing against a human-tested guide and independent sources.
2. **Coverage drives the rating.** A guide that never reads the page with the hard gate will confidently call the app "medium".
3. **Be as specific as the evidence.** A probe that found nothing useful now says so, rather than adding a weak "Tested" claim.
4. **The agent cannot replace trying it.** Registering, installing and submitting need an account and create real state, so the guide hands those steps to the developer and says why.
