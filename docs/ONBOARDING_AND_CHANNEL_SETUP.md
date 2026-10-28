# SME Onboarding and Channel Setup (Facebook Messenger + WhatsApp)

How a new SME goes from "just signed with us" to "receiving Facebook and WhatsApp messages in the inbox", step by step. Covers what our team does, what the SME does, what the SME must have ready, what each wizard screen shows, what happens behind the scenes, and what to do when something goes wrong.

> **Status:** MVP 1 plan, v0.1 (2026-10-28).
> **In MVP 1:** admin-created accounts, first-login password change, setup checklist, **Facebook Messenger wizard**, **WhatsApp wizard**, channel health, disconnect/reconnect, assisted setup.
> Related: spec §40–§42, [`ARCHITECTURE.md`](ARCHITECTURE.md) §7 and §9, [`DATABASE.md`](DATABASE.md) §5 and §7.

---

## 1. The whole journey at a glance

```text
 OUR TEAM (Platform Admin)                     SME OWNER
 ─────────────────────────                     ─────────
 0. Meta app ready (one-time, §2)
 1. Create tenant + package + dates
 2. Create Owner login
    → temporary password generated
 3. Share login details with SME  ─────────▶  4. Log in with temporary password
    (phone / WhatsApp / email)                5. Forced: set a new password
                                              6. Setup checklist appears
                                              7. Confirm business details
                                              8. Connect Facebook Page   (wizard A)
                                              9. Connect WhatsApp        (wizard B)
                                             10. Send a test message → see it in Inbox ✓
                                             11. Add products, add staff (optional now)
 Support: assisted setup call if stuck ◀────  "Need help?" button on every step
```

Target: an SME with everything ready (§4) completes steps 4–10 in **under 20 minutes**.

---

## 2. Step 0 — What WE must have ready first (one-time, before any SME)

None of the SME wizards work until our own Meta setup is done. This is the **longest lead-time item in the whole project** and must start immediately, in parallel with development.

| # | Item | Why | Owner | Typical lead time* |
|---|---|---|---|---|
| 1 | Meta Business portfolio for our company | owns the app | us | 1 day |
| 2 | **Business verification** of our company (registration certificate, PAN, address, domain/website) | required for advanced access and Tech Provider | us | days – 2 weeks |
| 3 | Meta developer app (type: Business) with products **WhatsApp** and **Messenger** and **Facebook Login for Business** | the thing SMEs authorize | dev | 1 day |
| 4 | Public **privacy policy**, **terms of service**, **data deletion instructions/callback URL**, app icon, support email | required for app review | us + dev | 2–3 days |
| 5 | Webhook callback URLs on HTTPS (`/api/v1/webhooks/whatsapp`, `/api/v1/webhooks/messenger`) and verify token | Meta sends messages here | dev | with Phase 3 |
| 6 | **App Review** for advanced access: `pages_show_list`, `pages_messaging`, `pages_manage_metadata`, `pages_read_engagement`, `business_management`, `whatsapp_business_management`, `whatsapp_business_messaging` | without it only our own test accounts can connect | dev (screencasts of working flows) | 1–3 weeks, may need resubmission |
| 7 | **Become a WhatsApp Tech Provider** and enable **Embedded Signup** | lets SMEs create/connect WhatsApp numbers inside our app | us + dev | after 2 and 6 |
| 8 | Two **Facebook Login for Business configurations** (one for Messenger, one for WhatsApp Embedded Signup) → configuration IDs in env | defines exactly which permissions the popup asks for | dev | 1 day |
| 9 | Test assets: test Facebook Page, test WhatsApp number (Meta test number + one real Nepali SIM) | end-to-end testing and app-review screencasts | dev | 1 day |

\* Lead times are typical, not guaranteed; Meta reviews can take longer and requirements change. Re-check Meta's current documentation when starting each item.

Until items 6–7 are approved, the app works in **development mode**: only people with a role on our Meta app (developers/testers) can connect. That is enough to build and test, and to record the app-review screencasts.

**Env/config needed** (adds to spec §51):

```env
META_APP_ID=
META_APP_SECRET=
META_GRAPH_API_VERSION=               # pin the current version at build time; upgrade deliberately
META_WEBHOOK_VERIFY_TOKEN=
META_LOGIN_CONFIG_ID_MESSENGER=
META_LOGIN_CONFIG_ID_WHATSAPP=        # Embedded Signup configuration
META_DATA_DELETION_CALLBACK_URL=
META_DEAUTHORIZE_CALLBACK_URL=
```

One Meta app serves both Messenger and WhatsApp (replaces the separate `WHATSAPP_APP_ID`/`WHATSAPP_APP_SECRET` in the spec).

---

## 3. Steps 1–5 — Account creation and first login

### 3.1 Platform admin creates the account

Platform Admin Console → **Tenants → New tenant**:

```text
┌ New tenant ─────────────────────────────────────────────┐
│ 1 Business   2 Package   3 Owner login   4 Review       │
├─────────────────────────────────────────────────────────┤
│ Business name*        [ Sharma Furniture             ]  │
│ Legal name            [ Sharma Furniture Pvt. Ltd.   ]  │
│ PAN / VAT no.         [ 6xxxxxxxx ]  VAT registered [✓] │
│ Phone*  [ +977 98XXXXXXXX ]  Email [ owner@...       ]  │
│ Address               [ Itahari-6, Sunsari           ]  │
│ Timezone [Asia/Kathmandu ▾]  Currency [NPR ▾]           │
│ Numbering [ Nepali fiscal year (2082-83) ▾ ]            │
└─────────────────────────────────────────────────────────┘
 Step 2: Package [Business ▾]  Cycle [Yearly ▾]  Price Rs. xx,xxx
         Trial [ ] / Start [2026-10-28]  Expiry [auto: 2027-10-27]
         Record payment now? [✓]  → method, reference, amount
 Step 3: Owner name*  [ Ram Sharma ]
         Login (email)* [ owner@sharmafurniture.com ]
         Mobile        [ +977 98XXXXXXXX ]
```

**Login ID = email address.** (Phone-number login is post-MVP.) If the owner has no email, our team helps create one before onboarding — email is needed for password reset and important notices.

### 3.2 Login details are generated

On **Create**, the system:

1. Creates the tenant, subscription, the Owner user and the OWNER membership in one transaction.
2. Generates a **temporary password** (14 characters, random, easy to read — no `0/O/1/l`).
3. Shows it **once** to the admin:

```text
┌ Login details for Ram Sharma ───────────────────────────┐
│ Login page:   https://app.<domain>/login                 │
│ Email:        owner@sharmafurniture.com                  │
│ Temporary password:  Kq7m-Rt4x-Wp9z      [Copy]          │
│ Valid until:  2026-11-04 (7 days)                        │
│                                                          │
│ [Copy message for WhatsApp]  [Email login details]       │
│ This password will not be shown again.                   │
└──────────────────────────────────────────────────────────┘
```

"Copy message for WhatsApp" copies a ready-made bilingual message (English + Nepali) with the link, email and temporary password, so the admin can paste it to the SME.

Rules:

- Stored only as an Argon2id hash; flagged `must_change_password = true`, `temp_password_expires_at = now + 7 days`.
- If it expires or is lost: admin clicks **Reset login → Generate new temporary password** (old one stops working immediately). Audit-logged.
- Admins never see or set the SME's real password.

### 3.3 SME first login → forced password change

```text
Login (email + temporary password)
   ↓
"Welcome, Ram! Please set your own password"   ← the only screen allowed
   New password  [            ]  ✓ at least 10 characters
   Confirm       [            ]  ✓ not a common password
   [Set password]
   ↓
All other sessions revoked, temporary password invalidated
   ↓
"Verify your email" banner (one click link sent to the email) — not blocking
   ↓
Setup checklist
```

Backend enforcement: while `must_change_password = true`, every API call except `change-password`, `me` and `logout` returns `403 password_change_required`. The frontend only shows the change-password screen.

Password policy: minimum 10 characters, checked against a common/breached-password list, no forced complexity rules. Email verification is needed before "forgot password" works for that account.

### 3.4 Staff accounts

The Owner (or an Admin) adds staff the same way: **Settings → Users → Add user** → name, email, role → temporary password shown once with "Copy message for WhatsApp" → staff must change it at first login. Plan limit `max_users` is checked first.

---

## 4. What the SME needs BEFORE starting (the "Before you start" page)

Shown in the checklist, as a printable page, and sent by our team with the login details. Most failed setups are caused by one of these.

### For Facebook Messenger

| ✔ | Requirement | How to check |
|---|---|---|
| ☐ | A **Facebook Page** for the business (not a personal profile) | facebook.com → your Page |
| ☐ | You log in with the **personal Facebook account that has full control** of that Page | Page → Settings → Page access → you are listed with **full control** |
| ☐ | You know that Facebook account's password, and can receive its login code (2FA) on your phone | — |
| ☐ | Page is **published** and **Messenger is turned on** (people can message the Page) | open the Page as a visitor — there is a "Message" button |
| ☐ | (If the Page belongs to a Business portfolio) you are an **admin** of that portfolio | business.facebook.com → Settings → People |
| ☐ | Use a **laptop/desktop browser** (Chrome/Edge) for setup; allow pop-ups | — |

### For WhatsApp — choose one of two options

**Option 1 — Use a new / dedicated number (recommended for most SMEs)**

| ✔ | Requirement |
|---|---|
| ☐ | A mobile number (NTC/Ncell) or landline that you own, that can receive an **SMS or voice call** right now |
| ☐ | The number is **not currently registered on WhatsApp** (normal or Business app). If it is, either use a different number, or delete the WhatsApp account on that number first (WhatsApp → Settings → Account → Delete account) — **this removes chat history on the phone** |
| ☐ | Business name you want customers to see (display name), e.g. "Sharma Furniture" — must match your business name/brand |
| ☐ | Business category, short description, address, website or Facebook Page link (optional but helps approval) |
| ☐ | The same Facebook account as above (it creates/uses the Meta Business portfolio) |

**Option 2 — Keep using the WhatsApp Business app on your phone (coexistence)**

| ✔ | Requirement |
|---|---|
| ☐ | The number is already on the **WhatsApp Business app** (not normal WhatsApp), updated to the latest version, and has been actively used |
| ☐ | The phone with the app is **with you** during setup (you scan a QR code) |
| ☐ | You accept that some app features behave differently once linked (Meta shows the list during setup) |

> Coexistence availability depends on the number's country and Meta's rollout. The wizard checks it; if not available for the number, the SME is guided to Option 1. **Verify Nepal (+977) availability during Phase 0 testing.**

### What the SME does NOT need

- No developer account, no API keys, no tokens to copy/paste.
- We **never** ask for their Facebook password — they type it only into Facebook's own window.
- No payment card for MVP 1 (we only send replies inside the 24-hour window). A payment method on the WhatsApp account will be needed later for template messages; the wizard mentions it as "later".

---

## 5. Step 6 — Setup checklist (first screen after password change)

```text
┌ Get started with <Product> ──────────────────── 2 of 7 done ─┐
│ ✅ Set your password                                          │
│ ✅ Confirm business details            (edit)                  │
│ ⬜ Connect your Facebook Page          [Connect]   ~5 min     │
│ ⬜ Connect WhatsApp                     [Connect]   ~10 min    │
│ ⬜ Send a test message                  [How?]                 │
│ ⬜ Add your products                    [Add]  (or import CSV*)│
│ ⬜ Add your staff                       [Add]                  │
│                                                               │
│ 📄 Before you start (what you need)   ☎ Book assisted setup   │
└───────────────────────────────────────────────────────────────┘
```

- Visible to OWNER/ADMIN until all channel steps are done (can be dismissed; reopen from Settings).
- Each item is live: it turns ✅ automatically (e.g. "Send a test message" turns ✅ when the first inbound message arrives on any connected channel).
- Facebook and WhatsApp can be done in any order; neither depends on the other.
- \* CSV import is post-MVP; manual add in MVP 1.

---

## 6. Wizard A — Connect Facebook Page (Messenger)

Location: **Channels → Facebook Messenger → Connect** (or from the checklist). Requires `channel.manage` (OWNER/ADMIN). Plan limit `max_messenger_pages` checked before start.

### Screens

```text
A1  Before you start
    ┌──────────────────────────────────────────────────────────┐
    │ Connect your Facebook Page                                │
    │ You will:                                                 │
    │  1. Log in to Facebook in a pop-up window                 │
    │  2. Choose your business Page(s)                          │
    │  3. Allow <Product> to read and reply to Page messages    │
    │ You need: the Facebook account with full control of the   │
    │ Page. [Check requirements]                                 │
    │ We never see your Facebook password.                      │
    │                         [Continue with Facebook]          │
    └──────────────────────────────────────────────────────────┘

A2  Facebook pop-up (Meta's screens, not ours)
    → Log in / "Continue as Ram"
    → Choose the business portfolio (if asked)
    → Select Page(s): ☑ Sharma Furniture   ☐ Ram's Other Page
    → Review permissions → [Save] / [Got it]
    (pop-up closes)

A3  Choose Pages to connect                      (our screen)
    ┌──────────────────────────────────────────────────────────┐
    │ Pages you allowed:                                        │
    │ ◉ Sharma Furniture          ✓ can be connected            │
    │ ○ Ram's Other Page          ✓ can be connected            │
    │ ✗ Old Shop Page             ⚠ you don't have full control │
    │ ✗ Sharma Traders            ⚠ already connected to another│
    │                               account — contact support   │
    │ Your package allows 1 Page.                               │
    │                                  [Connect selected Page]  │
    └──────────────────────────────────────────────────────────┘

A4  Connecting… (progress, ~5 sec)
    ✓ Saving secure access to your Page
    ✓ Subscribing to new messages
    ✓ Checking everything works

A5  Test it
    ┌──────────────────────────────────────────────────────────┐
    │ ✅ Sharma Furniture is connected                           │
    │ Now test it: from your personal Facebook / Messenger,     │
    │ send "Hello" to your Page.                                 │
    │                                                            │
    │ Waiting for your test message…  ⏳                         │
    │ → "Message received from Ram Sharma: Hello" ✅            │
    │                                   [Open Inbox]  [Done]    │
    └──────────────────────────────────────────────────────────┘
    (Test step can be skipped; the checklist item stays open.)
```

### What happens behind the scenes

| Step | Frontend | Backend |
|---|---|---|
| A1 | `POST /api/v1/channels/setup-sessions {provider: messenger}` → gets `session_id` + `state` | creates `channel_setup_sessions` row (state = random, expires 30 min); checks permission + plan limit |
| A2 | Opens Facebook Login for Business (JS SDK `FB.login` with `config_id = META_LOGIN_CONFIG_ID_MESSENGER`). The SDK is loaded and the setup session created *before* the click so the pop-up isn't blocked | — |
| A2→A3 | Receives the short-lived user token → `POST …/setup-sessions/{id}/authorize {state, access_token}` | validates `state`; **`debug_token` must show our app id, a valid token and the scopes `pages_show_list`, `pages_messaging`, `pages_manage_metadata`** (blocks tokens issued to other apps); exchanges for a **long-lived** user token; lists Pages (`/me/accounts`) with tasks; marks each Page connectable or not (needs `MANAGE`+`MESSAGING` tasks / already connected to another business / over plan limit); stores the user token **encrypted** for this session only |
| A3→A4 | `POST …/setup-sessions/{id}/complete {page_ids}` | for each Page: gets a fresh **Page access token**; subscribes the Page to our app (`POST /{page-id}/subscribed_apps` with `messages, message_echoes, message_deliveries, message_reads, messaging_postbacks`) and verifies by reading it back — **before** any DB write, so a failure changes nothing; then encrypts and stores the token in `channel_credentials`, creates/reuses `channel_connection` + `channel_account`; wipes the session user token; audit `CHANNEL_CONNECTED` |
| A5 | listens on SSE for `message.created` on this account | normal inbound pipeline; the first message also marks the checklist item done |

Nothing in A2 is our UI. If Meta changes its pop-up screens, our wizard still works — we only depend on the returned `code`.

### Errors and what the SME sees

| Situation | Message shown | Fix offered |
|---|---|---|
| Pop-up blocked | "Your browser blocked the Facebook window." | how to allow pop-ups; [Try again] |
| SME closed the pop-up / clicked Cancel | "Facebook connection was cancelled." | [Try again] |
| No Pages returned | "We couldn't find any Pages. You may be logged in with a different Facebook account, or you didn't select a Page." | [Check requirements] [Try again — choose Page] |
| No full control of the Page | "You need full control of this Page." | how to check/request Page access |
| Page already connected to another tenant | "This Page is already connected to another account." | [Contact support] (support can verify ownership and move it) |
| Plan limit reached | "Your package allows 1 Page." | [Request upgrade] |
| Permissions partly declined | "<Product> needs permission to manage messages for your Page." | [Try again] (re-request) |
| Subscribe call failed / Meta error | "Facebook didn't respond. Nothing was changed." | automatic retry ×3, then [Try again] / support with error code |
| App not yet approved (dev mode) | "Facebook connection is not yet available for your account." | internal: add tester role (pre-approval only) |

### Things to tell the SME (shown on A5 and in help)

- Messages to your Page now also appear in <Product>. You can still use Facebook/Messenger/Meta Business Suite as before.
- Replies sent from Facebook's own apps also show in <Product> (as "sent from Facebook").
- You can reply to a customer for **24 hours after their last message**. After that you must wait for them to message again (extended options come later).
- If you change your Facebook password, lose Page access, or remove <Product> from Facebook **Business Integrations**, the connection stops and you'll be asked to reconnect.
- If another chatbot tool is also connected to the Page, both receive messages — turn off auto-replies in one of them to avoid double replies.

---

## 7. Wizard B — Connect WhatsApp (Embedded Signup)

Location: **Channels → WhatsApp → Connect**. Requires `channel.manage`. Plan limit `max_whatsapp_numbers` checked before start.

### Screens

```text
B1  Choose how to connect
    ┌──────────────────────────────────────────────────────────┐
    │ Connect WhatsApp                                          │
    │ ◉ Use a new or dedicated number   (recommended)           │
    │   The number must not be on WhatsApp right now.           │
    │ ○ Keep using my WhatsApp Business app on this phone       │
    │   Chats appear both in the app and in <Product>.          │
    │                                                           │
    │ Have ready: the phone to receive a code (or scan a QR),   │
    │ your business name, category and address.                 │
    │ [Check requirements]                                       │
    │                         [Continue with Facebook]          │
    └──────────────────────────────────────────────────────────┘

B2  Meta Embedded Signup pop-up (Meta's screens)
    1. Log in to Facebook / "Continue as Ram"
    2. Business portfolio: choose existing or create
       (business name, email, website/Page, country = Nepal)
    3. WhatsApp Business Account: choose existing or create new
    4. WhatsApp business profile: display name, category, (description)
    5. Phone number
         Option 1: enter number → choose SMS or voice call
                   → enter 6-digit code
         Option 2: enter number → open WhatsApp Business app
                   → scan QR / confirm → choose to share chat history
    6. Review permissions → [Confirm] → Finished
    (pop-up closes)

B3  Finishing setup…                           (our screen, ~10 sec)
    ✓ Saving secure access
    ✓ Connecting +977 98XXXXXXXX
    ✓ Activating the number for messages
    ✓ Subscribing to new messages
    ✓ Checking everything works

B4  Connected
    ┌──────────────────────────────────────────────────────────┐
    │ ✅ WhatsApp connected: +977 98XXXXXXXX                     │
    │ Display name "Sharma Furniture":  ⏳ under review by Meta │
    │   (customers may see your number until it's approved —    │
    │    you can already receive and reply to messages)          │
    │                                                            │
    │ Test it: from another phone, send "Hello" on WhatsApp to   │
    │ +977 98XXXXXXXX                                            │
    │ Waiting for your test message…  ⏳ → ✅ received           │
    │                                   [Open Inbox]  [Done]    │
    └──────────────────────────────────────────────────────────┘
```

### What happens behind the scenes

| Step | Frontend | Backend |
|---|---|---|
| B1 | `POST /api/v1/channels/setup-sessions {provider: whatsapp, mode: new_number \| coexistence}` | creates setup session; permission + plan limit check |
| B2 | Loads Facebook JS SDK; `FB.login` with `config_id = META_LOGIN_CONFIG_ID_WHATSAPP`, `response_type=code`, `override_default_response_type`, `extras` (feature type for coexistence, session-info v3). Listens for the Embedded Signup `message` event → receives `waba_id`, `phone_number_id` (or cancel step / error) | — |
| B2→B3 | `POST …/setup-sessions/{id}/whatsapp {state, code, waba_id, phone_number_id}` | resumable steps, each recorded in the setup session: **token** (exchange the single-use `code` for the business integration token; kept encrypted in the session so a retry never needs the code again) → **verify** (`debug_token`: our app, valid, `whatsapp_business_management` + `whatsapp_business_messaging`, and granular scopes include this WABA; the phone number is in `/{waba_id}/phone_numbers`; not connected to another business; plan limit) → **subscribed** (`POST /{waba_id}/subscribed_apps`, verified by reading back) → **saved** (connection per WABA with the encrypted business token; account per number; audit `CHANNEL_CONNECTED`) → **registered** (new-number mode, only if the number isn't already on the Cloud API: `POST /{phone_number_id}/register` with a generated 6-digit PIN stored encrypted). Coexistence mode skips registration. Errors are returned *after* the progress commits, so "Try again" continues from the failed step |
| B4 | SSE for `message.created`; shows display-name status | beat job refreshes display-name status / quality rating daily; account webhooks update them live |

Each backend step is **idempotent and resumable**: the setup session records which steps succeeded, so if B3 fails halfway, [Try again] continues from the failed step instead of starting over in Meta's pop-up.

### Errors and what the SME sees

| Situation | Message shown | Fix offered |
|---|---|---|
| Closed pop-up / cancelled | "WhatsApp setup was cancelled at step: <step>." (from session info) | [Try again] — Meta remembers completed steps |
| Number already on WhatsApp (new-number mode) | "This number is already used on WhatsApp." | use another number, **or** switch to "Keep using my WhatsApp Business app" (if it's a Business app number), **or** delete the WhatsApp account on that phone first (warn: chat history lost) |
| Code (OTP) not received | (in Meta pop-up) | choose **voice call** instead of SMS; wait 1–2 min; check the number format (+977) |
| Coexistence not available for the number | "Keeping the app isn't available for this number yet." | use a new/dedicated number |
| Display name rejected by Meta | channel card shows ⚠ "Display name not approved" | edit name (must match business), resubmit; messaging continues meanwhile |
| Number already connected to another tenant | "This number is connected to another account." | [Contact support] |
| Business portfolio restricted / not verified limits | "Meta has limited this WhatsApp account." with Meta's reason | link to Meta's guidance; our support helps |
| Register step failed (e.g. two-step PIN already set by a previous provider) | "This number is protected by a PIN from a previous setup." | SME removes/resets two-step verification in WhatsApp Manager, then [Try again]; support guide |
| Plan limit reached | "Your package allows 1 WhatsApp number." | [Request upgrade] |
| App not approved / not Tech Provider yet | "WhatsApp connection is not yet available." | internal only during pre-launch |

### Things to tell the SME (shown on B4 and in help)

- **Who owns what:** the WhatsApp Business Account and number stay **yours** (in your Meta business portfolio). <Product> is given permission to use them; you can remove it at any time.
- **New-number mode:** this number now works only through <Product> (not in the WhatsApp phone app). Use <Product> on your phone browser (install it as an app from the browser menu).
- **Coexistence mode:** keep chatting in the WhatsApp Business app; messages appear in both places. Some app features are limited once linked (Meta lists them).
- **24-hour rule:** you can reply freely within 24 hours of the customer's last message. Messages outside 24 hours need approved templates — coming after MVP 1.
- **Display name:** Meta reviews it; until approved, customers may see your phone number.
- Don't spam or message people who didn't contact you — Meta lowers the number's quality rating and can block it.

---

## 8. After connection — channel health

**Channels page** shows one card per connected Page/number:

```text
┌ WhatsApp ───────────────────────────────┐ ┌ Facebook Messenger ─────────────────────┐
│ +977 98XXXXXXXX  "Sharma Furniture"     │ │ Sharma Furniture (Page)                 │
│ Status:   🟢 Healthy                    │ │ Status:   🟠 Action needed              │
│ Display name: ✅ Approved               │ │ Reason: Facebook access expired — you   │
│ Quality:  🟢 High                       │ │ changed your password or removed access │
│ Last message: 2 minutes ago             │ │ Last message: 3 days ago                │
│ Messages today: 184                     │ │                        [Reconnect]      │
│ [Details]  [Disconnect]                 │ │ [Details]  [Disconnect]                 │
└─────────────────────────────────────────┘ └─────────────────────────────────────────┘
```

| Status | Meaning | Detected by |
|---|---|---|
| 🟢 Healthy | token valid, webhook subscription present | daily token check + subscription check |
| 🟡 Pending | e.g. display name under review | WhatsApp account webhooks / daily check |
| 🟠 Action needed | token invalid/expired, Page access removed, app removed from Business Integrations, subscription missing, quality low | daily check, Meta error on send, deauthorize callback |
| 🔴 Disconnected | disconnected by user or by Meta (number banned/deleted) | user action / account webhooks |

- On 🟠/🔴: email + in-app notification to OWNER/ADMIN, banner in the Inbox ("Messenger is not receiving messages — reconnect").
- **Reconnect** runs the same wizard; it reuses the existing channel account so conversation history stays attached.
- "Last message N days ago" is informational only — a quiet Page is not an error.

### Disconnect

**Channels → card → Disconnect** (OWNER/ADMIN, confirm by typing the Page/number):

- unsubscribes our app from the Page/WABA, revokes stored tokens, marks the account `disconnected`;
- **all conversations, customers and orders are kept**; the inbox shows them read-only for that channel;
- WhatsApp: the number stays in the SME's WhatsApp Business Account on Meta. To use it in the phone app again, they remove the number in WhatsApp Manager (guide in help center).
- Audit `CHANNEL_DISCONNECTED`.

If the SME removes our app from Facebook settings instead, Meta calls our **deauthorize callback** → the account goes to 🟠 Action needed automatically.

---

## 9. Assisted setup (support)

Many SMEs will need help. MVP 1 support model:

- **"Need help?"** on every wizard screen → shows the requirements for that step + WhatsApp/phone number of our support + "Book a setup call".
- **Assisted setup call:** our team guides by phone/screen share. **The SME types their own Facebook password and codes**; our staff never ask for them or log in as the SME.
- **Platform admin view** of each tenant's setup: checklist progress, setup sessions (started/failed step/Meta error code), channel health, last webhook. No access to tokens.
- **Help pages** (English + Nepali), with screenshots: "Check you have full control of your Page", "Prepare a WhatsApp number", "Allow pop-ups", "OTP not received", "Display name rules", "Reconnect after password change".

---

## 10. What we store and why (for the SME privacy page)

| Data | Why | Where |
|---|---|---|
| Page id, name, picture; WABA id, phone number id, display number, display name | identify the connected channel | `channel_accounts` |
| Page access token / WhatsApp business token | read and send messages | `channel_credentials`, **encrypted**, never shown |
| Customer messages, names, phone numbers (WhatsApp), profile names | the inbox and customer history | tenant data, isolated per SME |
| Not stored | Facebook password, personal timeline, friends, posts, the SME's personal messages | — |

---

## 11. Data model additions

Added to `DATABASE.md`:

- `users.must_change_password`, `users.temp_password_expires_at`, `users.password_changed_at`
- `channel_setup_sessions` — one row per wizard attempt: `provider`, `mode`, `state_hash`, `status` (`started`, `authorized`, `completing`, `completed`, `failed`, `cancelled`, `expired`), `steps_completed` (jsonb), `last_error_code`, `last_error_message`, `meta_session_info` (jsonb, no tokens), `temp_credential_id` (encrypted, deleted on finish), `started_by`, `expires_at`, `channel_account_id` on success
- `channel_accounts`: `name_status` (WhatsApp display name review), `health_status`, `health_reason`, `last_health_check_at`, `coexistence` (bool)
- `tenant_onboarding` — checklist state per tenant (`dismissed_at`; item completion is derived from real data, not stored as flags)

## 12. API additions

```text
POST /api/v1/auth/change-password                       (also used for forced first change)
POST /api/v1/platform/tenants/{id}/owner/reset-login    → new temporary password (shown once)
POST /api/v1/users                                       → returns temporary password once

GET  /api/v1/onboarding/checklist
POST /api/v1/onboarding/checklist/dismiss

POST /api/v1/channels/setup-sessions                     {provider, mode}
POST /api/v1/channels/setup-sessions/{id}/authorize    {state, access_token}   (Messenger)
POST /api/v1/channels/setup-sessions/{id}/complete       {page_ids}                                   (Messenger)
POST /api/v1/channels/setup-sessions/{id}/whatsapp       {state, code?, waba_id, phone_number_id}     (WhatsApp, resumable)
POST /api/v1/channels/setup-sessions/{id}/cancel         {step?, error?}  (where Meta's window was closed)
GET  /api/v1/channels                                    (cards + health)
POST /api/v1/channels/{id}/disconnect

POST /api/v1/webhooks/meta/deauthorize                   (signed_request)
POST /api/v1/webhooks/meta/data-deletion                 (signed_request → confirmation code + status URL)
```

---

## 13. Acceptance criteria for MVP 1 (this part)

1. Platform admin can create a tenant with package and dates and an Owner login; the temporary password is shown once and expires in 7 days.
2. The Owner cannot do anything except change the password until it is changed; old temporary password then stops working.
3. The setup checklist shows after first login and updates automatically.
4. An Owner with a Page they fully control can connect it in ≤ 5 minutes **without our help**, and a test message sent to the Page appears in the Inbox within 10 seconds.
5. An Owner with a fresh number can connect WhatsApp in ≤ 10 minutes without our help, and a test message appears in the Inbox within 10 seconds; a reply from the Inbox reaches the phone.
6. Coexistence mode works for a number on the WhatsApp Business app (if Meta supports it for the number's country) — messages sent from the phone app appear in the Inbox as "sent from WhatsApp app".
7. Every error in §6 and §7 shows the listed message and fix; no raw Meta error is shown to the SME (error code is shown small for support).
8. No token ever appears in an API response, browser storage, log line or error message (automated test).
9. A Page/number already connected to tenant A cannot be connected to tenant B.
10. Changing the Facebook password (or removing the app) puts the channel into 🟠 Action needed within 24 hours (immediately via deauthorize callback), notifies the Owner, and Reconnect restores it with history intact.
11. Disconnect keeps all history and stops new messages.
12. All connect/disconnect/reset-login actions are in the audit log.

---

## 14. Plan and order of work

| Phase (spec §54) | Work in this area |
|---|---|
| **Phase 0 — start now, runs in parallel** | §2 items 1–4, 8, 9; app review submissions as soon as the flows work in dev mode; Tech Provider application |
| Phase 1 — Foundation | admin tenant creation, temporary password + forced change, staff users, checklist skeleton |
| Phase 2 — Customer + Inbox | webhook framework, setup-session framework, channel cards/health model |
| **Phase 3 — Facebook Messenger** | Wizard A, deauthorize/data-deletion callbacks, health checks, help pages; record app-review screencast |
| **Phase 4 — WhatsApp** | Wizard B (new number + coexistence), register/PIN, display-name status, help pages; record app-review screencast; Tech Provider go-live |
| Phase 8 — Hardening | pilot with 3–5 real SMEs using only the help pages; measure time-to-connect and failure points; fix copy and flows |

**Messenger is built before WhatsApp** (swapped from the earlier plan): it needs only Facebook Login, has a shorter approval path, and the setup-session, token and webhook machinery it forces us to build is reused by WhatsApp, whose Tech Provider approval takes longer anyway.

**Biggest risk:** Meta approvals (business verification, app review, Tech Provider) — not code. Without them, real SMEs cannot connect, even if the product is finished.
