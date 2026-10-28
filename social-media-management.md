# Production-Grade Multi-Tenant Social Commerce SaaS

## 1. PROJECT OBJECTIVE

Build a production-ready, secure, multi-tenant SaaS platform that connects SME businesses with their social/customer communication channels:

- WhatsApp Business Platform
- Facebook Messenger
- TikTok — **post-MVP**, subject to the capabilities and approvals available for the selected TikTok APIs (see §13)
- Architecture must allow future channels such as Instagram, Viber, Telegram and website chat

**MVP channels: WhatsApp and Facebook Messenger only.** See §46.

The core business concept is:

> Social Message → Customer → Lead → Order → Invoice → Delivery → Payment → Customer History

Any incoming customer message, enquiry, order or supported event from a connected channel must be captured into our system.

The system must identify the customer/requester, detect duplicate identities where safely possible, link the interaction to the existing customer record, preserve the complete conversation/order history, and allow the SME to manage the resulting business transaction.

The system must be designed as a SaaS product from the beginning.

This is NOT a single-company application.

It must support:

- multiple tenants/businesses
- multiple users per tenant
- multiple social accounts per tenant
- strict tenant data isolation
- role-based access control
- subscription-ready architecture
- audit logging
- secure OAuth/token management
- production-grade security
- scalable asynchronous processing

---

# 2. TECHNOLOGY STACK

Use the following preferred stack.

## Backend

- Python 3.12+
- FastAPI
- SQLAlchemy 2.x
- PostgreSQL 16+
- Alembic
- Pydantic v2
- Redis
- Celery or equivalent production-grade task queue
- httpx for external APIs
- PostgreSQL UUID type
- pytest
- Ruff
- mypy where practical

## Frontend

- Next.js latest stable version
- TypeScript
- App Router
- Tailwind CSS
- shadcn/ui or equivalent accessible component system
- React Query / TanStack Query
- React Hook Form
- Zod
- Recharts or equivalent for dashboards

## Infrastructure

- Docker
- Docker Compose for development
- Production-ready containerization
- Nginx or cloud load balancer
- PostgreSQL
- Redis
- Celery worker
- Celery beat where required
- Object storage compatible with S3
- HTTPS/TLS
- structured JSON logging

Production deployment must be compatible with:

- AWS
- Azure
- GCP
- DigitalOcean or equivalent VPS

Do not tightly couple the application to one cloud provider.

---

# 3. ARCHITECTURE PRINCIPLES

Use modular architecture.

Backend:

```text
app/
├── api/
│   ├── v1/
│   │   ├── auth/
│   │   ├── tenants/
│   │   ├── users/
│   │   ├── customers/
│   │   ├── conversations/
│   │   ├── messages/
│   │   ├── channels/
│   │   ├── products/
│   │   ├── leads/
│   │   ├── quotations/
│   │   ├── orders/
│   │   ├── invoices/
│   │   ├── deliveries/
│   │   ├── payments/
│   │   ├── dashboard/
│   │   ├── webhooks/
│   │   └── audit/
│
├── core/
│   ├── config.py
│   ├── security.py
│   ├── permissions.py
│   ├── logging.py
│   ├── database.py
│   └── exceptions.py
│
├── models/
├── schemas/
├── services/
├── repositories/
├── integrations/
│   ├── whatsapp/
│   ├── messenger/
│   ├── tiktok/
│   └── base.py
│
├── workers/
├── middleware/
└── main.py
```

Frontend:

```text
src/
├── app/
├── components/
├── features/
│   ├── dashboard/
│   ├── customers/
│   ├── conversations/
│   ├── channels/
│   ├── products/
│   ├── orders/
│   ├── quotations/
│   ├── invoices/
│   ├── deliveries/
│   ├── payments/
│   └── settings/
├── lib/
├── hooks/
├── services/
├── types/
└── middleware.ts
```

Do NOT create a monolithic backend.

---

# 4. MULTI-TENANCY

This is a fundamental requirement.

Every business/customer organization is a TENANT.

Example:

```text
Tenant A
 ├── Users
 ├── Customers
 ├── Products
 ├── Channels
 ├── Conversations
 ├── Orders
 ├── Invoices
 └── Payments

Tenant B
 ├── Users
 ├── Customers
 ├── Products
 ├── Channels
 ├── Conversations
 ├── Orders
 ├── Invoices
 └── Payments
```

Tenant A must NEVER be able to access Tenant B data.

Do not rely only on frontend filtering.

Tenant isolation must be enforced at the backend/service/repository/database level.

Every tenant-owned table must contain:

```text
tenant_id UUID NOT NULL
```

Use PostgreSQL Row-Level Security where practical for highly sensitive tenant data.

Implement automated tests specifically proving cross-tenant access is impossible.

---

# 5. UUID PRIMARY KEYS

Use UUID primary keys for all externally exposed and business entities.

Do not use sequential integer IDs for API-visible entities.

Preferred:

```text
UUIDv4
```

or preferably:

```text
UUIDv7
```

where the selected PostgreSQL/Python libraries support it reliably.

Example:

```text
id UUID PRIMARY KEY
```

Never expose:

```text
1
2
3
4
```

as business resource identifiers.

Do not assume UUIDs alone provide authorization security.

Authorization and tenant isolation are mandatory even with UUIDs.

External/provider IDs may be stored separately:

```text
provider_message_id
provider_customer_id
provider_conversation_id
provider_order_id
```

These must NOT be used as our primary keys.

---

# 6. CORE DATA MODEL

Design normalized PostgreSQL schemas.

Minimum entities:

## Platform

- tenants
- tenant_settings
- subscriptions
- plans
- users
- roles
- permissions
- role_permissions
- user_roles
- audit_logs

## Social channels

- channel_connections
- channel_accounts
- channel_credentials
- webhook_events
- webhook_event_attempts

## Customer

- customers
- customer_identities
- customer_addresses
- customer_tags
- customer_notes

## Communication

- conversations
- conversation_participants
- messages
- message_attachments
- message_events

## Business

- products
- product_variants
- product_prices
- inventory
- inventory_transactions

## Sales

- leads
- quotations
- quotation_items
- orders
- order_items
- invoices
- invoice_items

## Delivery

- deliveries
- delivery_items
- delivery_status_history

## Payment

- payments
- payment_transactions
- payment_status_history

## Automation

- automation_rules
- automation_events
- notifications
- scheduled_followups

---

# 7. CUSTOMER IDENTITY RESOLUTION

This is one of the most important features.

A customer may contact a business from:

```text
WhatsApp
Messenger
TikTok
Phone
Email
Website
```

The system should attempt to identify whether the incoming identity already exists.

Create:

```text
customers
customer_identities
```

Example:

```text
Customer
UUID: xxx

Name: Ram Sharma
Phone: +97798XXXXXXXX
Email: example@email.com

Identities:

WhatsApp:
provider = whatsapp
provider_user_id = ...

Messenger:
provider = messenger
provider_user_id = ...

TikTok:
provider = tiktok
provider_user_id = ...
```

IMPORTANT:

Never automatically merge customers merely because names match.

Use confidence-based matching.

Possible matching priority:

1. verified provider identity
2. exact normalized phone
3. exact verified email
4. tenant-specific external customer ID
5. carefully scored combination of name/address/phone

If confidence is uncertain:

```text
Possible duplicate customer
```

Ask an authorized user to merge.

Customer merge must be auditable and reversible where practical.

---

# 8. MESSAGE INGESTION PIPELINE

Every channel webhook should follow a common pipeline.

```text
Provider
   ↓
Webhook Endpoint
   ↓
Signature Verification
   ↓
Raw Event Validation
   ↓
Idempotency Check
   ↓
Store Raw Event
   ↓
Queue Background Job
   ↓
Normalize Event
   ↓
Resolve Tenant
   ↓
Resolve Customer
   ↓
Create Conversation
   ↓
Create Message
   ↓
Extract Business Intent
   ↓
Create/Update Lead or Order
   ↓
Notify User
```

Webhook endpoints must return quickly.

Do not perform expensive processing inside the webhook request.

Use Redis + Celery/background workers.

---

# 9. WEBHOOK SECURITY

All supported provider webhooks must implement:

- provider signature validation
- timestamp/replay protection where available
- idempotency
- event deduplication
- payload validation
- rate limiting
- structured logging
- dead-letter/retry mechanism

Never trust a webhook merely because it contains a provider ID.

Never process the same event twice.

Create:

```text
webhook_events
```

with:

```text
id UUID
tenant_id UUID
provider
event_type
provider_event_id
payload_hash
received_at
processed_at
processing_status
retry_count
error_message
```

Unique constraint:

```text
(provider, provider_event_id)
```

where provider event IDs are available.

---

# 10. SOCIAL CHANNEL ADAPTER ARCHITECTURE

Create an abstract interface.

Example:

```python
class SocialChannelAdapter(ABC):

    async def validate_webhook(...):
        ...

    async def parse_webhook(...):
        ...

    async def send_message(...):
        ...

    async def send_media(...):
        ...

    async def get_customer_profile(...):
        ...

    async def refresh_token(...):
        ...

    async def disconnect(...):
        ...
```

Implement:

```text
WhatsAppAdapter
MessengerAdapter
TikTokAdapter
```

Do NOT put provider-specific logic inside generic business services.

The application should be able to add:

```text
InstagramAdapter
TelegramAdapter
ViberAdapter
```

without rewriting the order system.

---

# 11. WHATSAPP

Implement official WhatsApp Business Platform/Cloud API integration.

Do not use unofficial WhatsApp Web automation.

Support:

- OAuth/business connection where applicable
- webhook verification
- inbound text
- supported media
- customer identity
- outbound messages
- message status
- conversation association
- provider message IDs
- retry handling
- token management

Build a configuration screen:

```text
Settings
 → Channels
   → WhatsApp
      → Connect
      → Connected account
      → Phone number
      → Business account
      → Webhook status
      → Token status
      → Disconnect
```

Never expose access tokens in the frontend.

---

# 12. FACEBOOK MESSENGER

Use official Meta APIs.

Support:

- Facebook Page connection
- OAuth
- page authorization
- webhook subscription
- inbound messages
- customer identity
- outbound responses
- message status where available
- page/account association
- provider IDs

Configuration:

```text
Settings
 → Channels
   → Messenger
      → Connect Facebook Page
      → Select Page
      → Verify
      → Connected
```

Never store Facebook passwords.

---

# 13. TIKTOK (POST-MVP)

> **Not part of the MVP.** TikTok's messaging/DM API access for third-party apps is limited and approval-dependent. Do not build TikTok features in the MVP. The generic `SocialChannelAdapter` interface (§10) must still allow a TikTok adapter to be added later without changing business services.
>
> In the MVP, customers who discover the business on TikTok and then message via WhatsApp/Messenger are attributed through the order's **source** field (see §16) — e.g. staff select "TikTok" as the lead source.

Create TikTok as a provider adapter.

Do not hard-code unsupported assumptions.

Before implementing each capability, verify the current official TikTok API documentation and required scopes/review requirements.

At minimum design the adapter so that the application can support available TikTok capabilities such as:

- OAuth authorization
- account connection
- profile information
- supported content/event integration
- supported messaging capabilities if approved/available
- content publishing where authorized
- webhook/event handling where supported

TikTok's current Content Posting API uses OAuth/access tokens and requires approved scopes such as `video.publish` or `video.upload`; production apps are subject to TikTok's review requirements.

Do not make the entire product dependent on a TikTok capability until it has been verified for the production application.

Create feature flags:

```text
TIKTOK_MESSAGING_ENABLED
TIKTOK_CONTENT_POSTING_ENABLED
TIKTOK_WEBHOOKS_ENABLED
```

---

# 14. UNIFIED INBOX

Create a central interactive inbox.

Example:

```text
┌───────────────────────────────────────────────────────┐
│ Unified Inbox                                         │
├───────────────┬───────────────────────────────────────┤
│ Conversations │ Conversation                          │
│               │                                       │
│ 🔵 Ram        │ Ram: Do you have office chairs?      │
│ 🟢 Sita       │                                       │
│ 🟣 Hari       │ You: Yes, we have 20 available.      │
│               │                                       │
│ 🔵 5 new      │ Ram: What is the price?              │
│               │                                       │
│               │ [ Reply... ] [Create Quote]           │
└───────────────┴───────────────────────────────────────┘
```

Filters:

- All
- Unread
- WhatsApp
- Messenger
- TikTok (post-MVP)
- Leads
- Orders
- Payment pending
- Delivery pending
- Assigned to me

---

# 15. CUSTOMER 360

Every customer must have a 360-degree profile.

Example:

```text
Ram Sharma

Channels:
WhatsApp
Messenger
TikTok

Total Orders:
27

Total Sales:
Rs. 8,75,000

Outstanding:
Rs. 65,000

Last Order:
2026-09-15

Conversation History
───────────────────
WhatsApp
Messenger

Orders
───────────────────
ORD-xxx
ORD-xxx

Payments
───────────────────
PAY-xxx

Delivery
───────────────────
DEL-xxx
```

This is one of the key product differentiators.

---

# 16. ORDER MANAGEMENT

Order lifecycle:

```text
NEW
 ↓
CONFIRMED
 ↓
PROCESSING
 ↓
READY_FOR_DELIVERY
 ↓
OUT_FOR_DELIVERY
 ↓
DELIVERED
```

Alternative:

```text
CANCELLED
REJECTED
RETURNED
```

Every status change must be recorded.

Create:

```text
order_status_history
```

Every order must record where it came from:

```text
source_channel        whatsapp | messenger | phone | walk_in | other
source_conversation_id  (nullable, link to the conversation it was created from)
lead_source           optional, staff-selected: tiktok | facebook_post | instagram | referral | other
created_at
created_by
```

`source_channel` is the channel the order was taken on. `lead_source` is where the customer discovered the business (e.g. they saw a TikTok video, then messaged on WhatsApp). Both are used for channel/revenue reporting.

Never overwrite history without retaining an audit trail.

---

# 17. DELIVERY MANAGEMENT

**MVP: delivery is done manually by the business (own staff or a courier of their choice). The system only keeps a record of it.** No courier API integration in the MVP.

The system must answer: *Was this order delivered? By whom? When? Is it pending?*

Delivery entity:

```text
delivery_id
order_id
tenant_id
delivery_address
contact_name
contact_phone
delivery_method      own_staff | courier | customer_pickup
courier_name         free text, e.g. "Pathao", "Nepal Can Move" (nullable)
tracking_reference   free text (nullable)
assigned_to          user (nullable)
delivery_status
scheduled_date
delivered_at
delivery_notes
updated_by
```

Staff update the status manually. Every status change is stored in `delivery_status_history` with who changed it and when.

Status:

```text
PENDING
ASSIGNED
PICKED_UP
OUT_FOR_DELIVERY
DELIVERED
FAILED
RETURNED
```

Provide dashboard cards:

```text
Today's deliveries: 18
Pending: 7
Out for delivery: 6
Delivered: 5
```

---

# 18. PAYMENT MANAGEMENT

**MVP: payment is collected manually outside the system (cash, COD, eSewa, Khalti, Fonepay QR, bank transfer, cheque). The system only records whether payment was received, how much, by which method, and when.** No payment gateway integration in the MVP.

The system must answer: *Has this order/invoice been paid? Fully or partly? How? When? Who recorded it?*

A payment record is entered by a staff user (`payment.write` permission):

```text
payment_id
tenant_id
invoice_id / order_id
amount
payment_method       cash | cod | esewa | khalti | fonepay | bank_transfer | cheque | other
transaction_reference  free text, e.g. eSewa transaction ID (nullable)
paid_at              date/time the money was received
recorded_by          user
recorded_at
notes
```

Multiple payment records per invoice are allowed (partial payments). The invoice's `amount_paid`, `amount_due` and payment status are derived from its payment records — never typed in directly.

Correcting a payment is done by voiding the record (with a reason) and entering a new one — never by silent edit or hard delete. Voids are audit-logged.

Payment status:

```text
UNPAID
PARTIAL
PAID
OVERDUE
REFUNDED
```

Track:

```text
invoice_total
amount_paid
amount_due
due_date
payment_method
transaction_reference
paid_at
```

`OVERDUE` is computed from `due_date` and `amount_due`, not set manually.

Do not build payment gateway integration in MVP.

**Post-MVP only:** keep this abstraction in mind so gateways (eSewa, Khalti, Fonepay) can be added later without changing the payment records model. Do not implement it in the MVP.

```python
class PaymentProvider:
    async def create_payment_request(...):
        ...

    async def verify_payment(...):
        ...

    async def refund(...):
        ...
```

Then future providers can be added.

---

# 19. ORDER FROM CONVERSATION

Provide an important feature:

```text
Conversation
    ↓
Create Lead
    ↓
Create Quotation
    ↓
Convert to Order
```

Example:

Customer:

> I need 20 office chairs.

Employee clicks:

```text
[Create Order]
```

System pre-fills:

```text
Customer
Product
Quantity
Source conversation
Channel
```

User confirms.

No duplicate typing.

---

# 20. AI-ASSISTED ORDER EXTRACTION

Design an optional AI service.

Input:

```text
"I need 20 black office chairs and 5 tables. Can you deliver to Itahari?"
```

Output:

```json
{
  "intent": "purchase_request",
  "items": [
    {
      "product_hint": "office chair",
      "quantity": 20,
      "attributes": {
        "color": "black"
      }
    },
    {
      "product_hint": "table",
      "quantity": 5
    }
  ],
  "delivery_location": "Itahari"
}
```

IMPORTANT:

AI must not directly create financial transactions without configurable human approval.

Use:

```text
AI suggestion
→ Human confirmation
→ Transaction
```

Allow tenants to configure automation levels.

---

# 21. PRODUCT CATALOGUE

Products:

- SKU
- name
- description
- category
- price
- tax
- stock
- active/inactive
- images
- variants

AI should be able to match a customer's natural-language product request to the catalogue.

Example:

Customer:

> "20 ota 4 feet ko table chahiyo."

System:

```text
Matched:
4 Feet Office Table
SKU: TB-004
Confidence: 94%
```

User confirms.

---

# 22. DASHBOARD

Create a highly interactive dashboard.

Top-level metrics:

```text
Today's Sales
New Messages
New Leads
New Orders
Pending Orders
Pending Payments
Today's Deliveries
Overdue Payments
```

Charts:

### Sales

- daily
- weekly
- monthly

### Orders

- by channel
- by status

### Leads

- WhatsApp
- Messenger
- TikTok

### Conversion

```text
Messages
 ↓
Leads
 ↓
Quotes
 ↓
Orders
 ↓
Revenue
```

### Customer activity

- new customers
- returning customers
- repeat purchases

---

# 23. SOCIAL COMMERCE ANALYTICS

Create an innovative dashboard:

```text
Channel Performance

WhatsApp
Messages: 820
Leads: 320
Orders: 102
Revenue: Rs. 7.2L

Messenger
Messages: 420
Leads: 120
Orders: 31
Revenue: Rs. 1.9L

TikTok
Messages: 650
Leads: 280
Orders: 72
Revenue: Rs. 4.6L
```

This lets the SME understand which channel actually generates business.

---

# 24. CONVERSATION → REVENUE FUNNEL

Create:

```text
1,000 Messages
      ↓
420 Leads
      ↓
210 Quotations
      ↓
105 Orders
      ↓
Rs. 12,50,000 Revenue
```

Allow filtering:

- channel
- date
- product
- salesperson
- campaign
- customer

This can become a major SaaS selling point.

---

# 25. FOLLOW-UP AUTOMATION

If:

```text
Quotation sent
AND
No response for X days
```

create:

```text
Follow-up task
```

Do not automatically send messages unless the tenant has explicitly enabled automation.

Allow:

```text
Manual
Approval required
Fully automated
```

per automation rule.

---

# 26. SECURITY

Security is the highest priority.

Implement:

### Authentication

- secure password hashing using Argon2id
- access tokens with short expiry
- refresh token rotation
- secure HTTP-only cookies where appropriate
- MFA/TOTP-ready architecture
- account lock/rate limiting
- password reset with expiring tokens
- email verification

### Authorization

RBAC:

```text
OWNER
ADMIN
MANAGER
SALES
DELIVERY
ACCOUNTANT
VIEWER
```

Permissions:

```text
conversation.read
conversation.write
customer.read
customer.write
order.read
order.write
invoice.read
invoice.write
payment.read
payment.write
channel.manage
user.manage
settings.manage
```

Never rely solely on frontend permissions.

---

# 27. TOKEN SECURITY

Social platform access tokens are extremely sensitive.

NEVER:

- expose tokens to frontend
- store tokens in browser localStorage
- log access tokens
- put tokens in error messages
- commit secrets into Git

Store credentials encrypted at rest.

Preferred architecture:

```text
Database
    ↓
Encrypted credential blob
    ↓
KMS/application encryption key
```

Use environment-based master encryption keys in MVP.

Design for AWS KMS / Azure Key Vault / GCP KMS integration later.

Implement token rotation and revocation.

---

# 28. DATA PRIVACY

Customer data is sensitive.

Implement:

- data minimization
- tenant isolation
- encryption in transit
- encryption at rest
- audit logs
- access logs
- retention policies
- deletion/anonymization workflows
- export customer data
- tenant data export
- tenant deletion
- consent tracking where required
- privacy policy URL
- terms URL

Do not store information that is unnecessary for business functionality.

---

# 29. AUDIT LOGGING

Every important action must be auditable.

Example:

```text
User:
UUID

Action:
ORDER_STATUS_CHANGED

Resource:
Order UUID

Before:
PROCESSING

After:
DELIVERED

Timestamp:
2026-09-16T...

IP:
...

User Agent:
...
```

Audit:

- login
- logout
- failed login
- customer merge
- order creation
- order modification
- invoice creation
- payment modification
- channel connection
- channel disconnection
- permission changes
- user creation
- user deletion
- data export
- sensitive settings changes

Audit logs must be append-only from the application perspective.

---

# 30. API SECURITY

Implement:

- CORS allowlist
- CSRF protection where cookie authentication is used
- rate limiting
- request validation
- maximum payload sizes
- secure headers
- API versioning
- pagination
- filtering
- sorting
- authorization checks
- SQL injection protection through ORM/parameterized queries
- SSRF protection for external URLs
- file upload validation
- MIME validation
- malware scanning architecture for uploaded files
- webhook signature validation

Never trust user-supplied URLs.

---

# 31. FILE/MEDIA STORAGE

Do not store large media files directly in PostgreSQL.

Use:

```text
S3-compatible object storage
```

Database stores:

```text
object_key
mime_type
size
checksum
storage_provider
```

Use signed URLs for private files.

Never expose bucket credentials to frontend.

---

# 32. API DESIGN

Use REST API.

Example:

```text
/api/v1/auth/login
/api/v1/auth/refresh

/api/v1/tenants
/api/v1/users

/api/v1/channels
/api/v1/channels/{id}/connect
/api/v1/channels/{id}/disconnect

/api/v1/customers
/api/v1/customers/{id}

/api/v1/conversations
/api/v1/conversations/{id}/messages

/api/v1/products

/api/v1/leads
/api/v1/quotations
/api/v1/orders
/api/v1/invoices
/api/v1/deliveries
/api/v1/payments

/api/v1/dashboard

/api/v1/webhooks/whatsapp
/api/v1/webhooks/messenger
/api/v1/webhooks/tiktok        (post-MVP)
```

Use OpenAPI documentation.

---

# 33. IDEMPOTENCY

All business-critical POST endpoints should support idempotency where appropriate.

Example:

```text
Idempotency-Key: UUID
```

Especially:

- payment
- order creation
- invoice creation
- outbound messaging
- webhook processing

Prevent duplicate orders and duplicate payments.

---

# 34. OUTBOUND MESSAGE QUEUE

Never directly depend on social API calls during normal user HTTP requests when reliability matters.

Use:

```text
API
 ↓
OutboundMessage
 ↓
Redis/Celery
 ↓
Provider Adapter
 ↓
WhatsApp/Messenger/TikTok
```

Track:

```text
QUEUED
SENDING
SENT
DELIVERED
READ
FAILED
```

Retry transient failures with exponential backoff.

Do not retry permanent provider errors indefinitely.

---

# 35. OBSERVABILITY

Implement:

- structured JSON logs
- request ID
- correlation ID
- tenant ID in internal logs
- error tracking
- metrics
- health endpoints

Endpoints:

```text
/health
/health/live
/health/ready
```

Do not expose sensitive internal information through health endpoints.

Production should be compatible with:

- Sentry
- Prometheus
- Grafana
- OpenTelemetry

---

# 36. DATABASE REQUIREMENTS

Use:

- foreign keys
- unique constraints
- check constraints
- indexes
- composite indexes
- partial indexes where useful
- created_at
- updated_at
- soft deletion where appropriate

All timestamps should be stored in UTC.

Frontend converts to tenant/user timezone.

Use Nepal timezone:

```text
Asia/Kathmandu
```

as the default tenant timezone, but do not hard-code it globally.

---

# 37. DATABASE INDEXING

Create indexes for common queries:

```text
tenant_id
tenant_id + created_at
tenant_id + status
tenant_id + phone
tenant_id + email
tenant_id + provider
tenant_id + provider_customer_id
tenant_id + provider_message_id
tenant_id + order_number
tenant_id + invoice_number
```

Use PostgreSQL `EXPLAIN ANALYZE` during performance testing.

---

# 38. ORDER NUMBER

Use UUID internally.

Human-readable order number separately:

```text
ORD-2026-000001
```

Do NOT use the order number as the primary key.

Same principle:

```text
Invoice:
INV-2026-000001

Quotation:
QUO-2026-000001
```

These are tenant-scoped human-readable references.

---

# 39. FRONTEND UX

Use a professional SaaS dashboard.

Left navigation:

```text
Dashboard

Inbox
  ├── All
  ├── WhatsApp
  └── Messenger
      (TikTok / Instagram added post-MVP)

Customers

Sales
  ├── Leads
  ├── Quotations
  └── Orders

Products

Invoices

Delivery

Payments

Reports

Automation

Channels

Settings
```

Responsive design.

Mobile-friendly because many SME users will use phones/tablets.

---

# 40. CHANNEL CONNECTION WIZARD

Make connection extremely simple. **MVP 1 includes the Facebook Messenger and WhatsApp wizards in full — detailed in `docs/ONBOARDING_AND_CHANNEL_SETUP.md` (§6 Facebook, §7 WhatsApp).**

```text
Channels

WhatsApp
[Connect]

Messenger
[Connect]

TikTok / Instagram
(post-MVP)
```

Click:

```text
Connect WhatsApp
     ↓
OAuth / provider authorization
     ↓
Select Business Account
     ↓
Select Page/Phone
     ↓
Verify
     ↓
Webhook status
     ↓
Connected ✓
```

Show:

```text
Connection Status: Healthy
Last webhook: 2 minutes ago
Token status: Valid
Messages today: 184
```

Never ask users to manually paste access tokens unless the provider explicitly requires it for a controlled setup.

---

# 41. TENANT ONBOARDING

**MVP: onboarding is done by our team (platform admin), not self-service.** When an SME signs up with us, a platform admin sets up their account:

```text
Platform Admin Console
     ↓
Create Tenant (business information)
     ↓
Select Package (plan) + billing cycle
     ↓
Set subscription start date / expiry date (or trial)
     ↓
Record subscription payment (manual)
     ↓
Create Owner login (email) → temporary password generated (shown once, valid 7 days)
     ↓
Admin shares login details with the SME (copy-for-WhatsApp message or email)
     ↓
Owner logs in → forced to set own password → verifies email
     ↓
Setup checklist: Connect Facebook Page (wizard) → Connect WhatsApp (wizard)
     → Send test message → Add Products → Add Staff
     ↓
Dashboard
```

Self-service sign-up (Create Account → Create Business → choose plan) is post-MVP, but the data model must not prevent it.

**The complete step-by-step onboarding and channel connection plan — requirements the SME needs ready, every wizard screen, behind-the-scenes steps, errors, health, disconnect and acceptance criteria — is in `docs/ONBOARDING_AND_CHANNEL_SETUP.md`.**

Each tenant should have:

```text
business_name
legal_name
address
phone
email
tax_number
currency
timezone
logo
```

---

# 42. SAAS SUBSCRIPTIONS (MVP)

**Subscriptions are part of the MVP.** Every tenant must have a subscription with a package, price, status and expiry date. Subscription payments are collected manually (bank transfer, eSewa, Khalti, Fonepay, cash, cheque) and recorded by a platform admin — no online billing gateway in the MVP.

## Platform vs tenant users

Platform (our team) users are separate from tenant users and are not members of any tenant:

```text
PLATFORM_SUPER_ADMIN   full platform access, manage plans and prices
PLATFORM_ADMIN         create/manage tenants and subscriptions, record subscription payments
PLATFORM_SUPPORT       read-only tenant/subscription info for support
```

Platform users access tenants only through the Platform Admin Console. Every platform action on a tenant is audit-logged.

## Tables

```text
plans
plan_prices
plan_features
subscriptions
subscription_history
subscription_payments
usage_records
```

### plans (packages)

```text
id
code               PLAN_BASIC | PLAN_BUSINESS | PLAN_PRO (configurable, not hard-coded)
name
description
is_active          inactive plans cannot be assigned to new tenants
sort_order
```

### plan_prices

```text
id
plan_id
billing_cycle      monthly | quarterly | half_yearly | yearly
currency           default NPR
amount
is_active
effective_from
```

Price changes create a new price row; existing subscriptions keep the price they were sold at.

### plan_features (entitlements / limits)

```text
plan_id
feature_key        e.g. max_users, max_channels, max_whatsapp_numbers,
                   max_messenger_pages, max_products, max_monthly_orders,
                   storage_mb, feature.invoice_pdf, feature.reports
value              integer / boolean / null = unlimited
```

### subscriptions

```text
id
tenant_id
plan_id
plan_price_id
price_amount       snapshot of the agreed price
currency
billing_cycle
discount_amount    optional, with reason
status
trial_ends_at      nullable
start_date
expiry_date
grace_period_days  default from settings, e.g. 7
auto_renew         false in MVP (renewal is manual)
cancelled_at
cancel_reason
notes
created_by         platform user
```

One active subscription per tenant at a time (enforce with a partial unique index).

### subscription_payments

```text
id
subscription_id
tenant_id
amount
payment_method     bank_transfer | esewa | khalti | fonepay | cash | cheque | other
transaction_reference
paid_at
period_start
period_end
recorded_by        platform user
receipt_number     human-readable, e.g. SUB-2026-000001
notes
voided_at / void_reason
```

Same correction rule as tenant payments: void and re-enter, never silent edit.

## Subscription status

```text
TRIAL       trial period, full plan features
ACTIVE      paid and within expiry_date
GRACE       expiry_date passed, within grace period — full access, warning banner
EXPIRED     grace period ended — read-only access
SUSPENDED   manually suspended by platform admin (e.g. non-payment, abuse)
CANCELLED   ended by request
```

Status transitions are computed by a scheduled job (Celery beat, daily) from `trial_ends_at`, `expiry_date` and `grace_period_days`, plus manual admin actions. Every change is stored in `subscription_history` and audit-logged.

## Access enforcement (backend, not only frontend)

```text
TRIAL / ACTIVE / GRACE   full access within plan limits
EXPIRED                  read-only: can view and export data; cannot create orders,
                         send messages, or add users/channels.
                         Inbound webhooks are STILL stored so no customer messages are lost.
SUSPENDED                login blocked except for Owner (sees a "contact us" page);
                         inbound webhooks still stored
CANCELLED                as SUSPENDED; data retained per retention policy, then deletion workflow
```

Plan limits are checked in a single entitlement service (e.g. `entitlements.check(tenant_id, "max_users")`), never scattered as hard-coded numbers.

## Renewal (manual in MVP)

```text
Platform admin records subscription payment
     ↓
Selects period → new expiry_date calculated from billing cycle
     ↓
Status → ACTIVE
```

Upgrade/downgrade: platform admin changes plan; takes effect immediately or at next renewal (admin chooses). If a downgrade puts the tenant over a limit (e.g. too many users), existing items are kept but new ones are blocked until under the limit.

## Expiry reminders

- Email (and in-app banner) to tenant Owner at 15, 7, 3 and 1 days before expiry, and on entering GRACE / EXPIRED
- Platform admin list of subscriptions expiring in the next 30 days

## Tenant view

Settings → Subscription shows: current package, price, billing cycle, status, start date, expiry date, days remaining, plan limits vs current usage, and subscription payment history (receipts). Tenants cannot change their own plan in the MVP; a "Request upgrade/renewal" button notifies our team.

## Platform Admin Console

- tenants list with plan, status, expiry date, filters (expiring soon, grace, expired, suspended)
- create/edit tenant
- assign/change plan
- set trial / start / expiry dates
- record subscription payment and download receipt
- suspend / reactivate / cancel
- manage plans, prices and features (super admin only)
- platform metrics: active tenants, MRR, renewals due, expired tenants

---

Possible future billing dimensions:

- users
- connected channels
- conversations
- messages
- AI usage
- orders
- storage

Implement feature flags/entitlements.

Example:

```text
PLAN_BASIC
PLAN_BUSINESS
PLAN_PRO
```

Do not hard-code limits throughout application code.

---

# 43. AI ARCHITECTURE

AI must be an independent service.

```text
Conversation
      ↓
AI Service
      ↓
Intent
Entity Extraction
Product Matching
Suggested Reply
Order Suggestion
      ↓
Human Approval
```

Use provider abstraction:

```python
class AIProvider:
    async def classify_message(...)
    async def extract_order(...)
    async def suggest_reply(...)
```

This allows future support for:

- OpenAI
- Anthropic
- local models

Do not tightly couple the application to one LLM.

---

# 44. AI PRIVACY

Do not send unnecessary personal information to an AI provider.

Before AI processing:

```text
Data minimization
↓
Redaction where possible
↓
AI processing
```

Make AI provider configurable per tenant/system.

Store:

```text
ai_request_id
model
purpose
token usage
latency
status
```

Do not store full prompts/responses indefinitely unless explicitly required.

---

# 45. INNOVATIVE FEATURES TO DESIGN FOR

## A. Conversation-to-Order

One click:

```text
Conversation
→ Create Order
```

## B. AI Product Matching

Customer's natural language automatically matched to catalogue.

## C. Customer 360

All channels and transactions connected.

## D. Social Revenue Attribution

```text
TikTok → Revenue
WhatsApp → Revenue
Messenger → Revenue
```

## E. Follow-up Assistant

Automatically identify unanswered quotations/leads.

## F. Duplicate Customer Detection

Prevent fragmented customer histories.

## G. Smart Inbox

Automatically classify:

```text
QUESTION
PRICE_REQUEST
ORDER
COMPLAINT
SUPPORT
PAYMENT
DELIVERY
OTHER
```

## H. Unified Customer Timeline

```text
TikTok message
↓
WhatsApp
↓
Quotation
↓
Order
↓
Delivery
↓
Payment
```

## I. Business AI Assistant

Example:

> "Show me customers who asked about office chairs this week but didn't purchase."

or:

> "Which social channel generated the most orders this month?"

or:

> "Show me unpaid invoices older than 15 days."

---

# 46. MVP SCOPE

Do NOT attempt to build everything initially.

MVP principle: **capture every conversation and order, and keep an accurate record of what was delivered and paid. Payment and delivery happen in the real world; the system records them.**

MVP flow:

```text
WhatsApp / Messenger message
   ↓
Customer identified / created
   ↓
Order created from conversation (source channel recorded)
   ↓
Invoice (PDF)
   ↓
Delivery recorded manually  → delivered? when? by whom?
   ↓
Payment recorded manually   → paid? how much? which method? when?
   ↓
Customer history + dashboard
```

MVP must include:

### Authentication

- platform admin creates the Owner login; system generates a temporary password (shown once, 7-day expiry) that the admin shares with the SME (no public self-registration in MVP)
- login
- forced password change at first login (nothing else accessible until changed)
- email verification
- password reset
- Owner/Admin add staff the same way (temporary password + forced change)

### Onboarding and channel connection (see `docs/ONBOARDING_AND_CHANNEL_SETUP.md`)

- setup checklist after first login (auto-updating)
- "Before you start" requirements page (English + Nepali)
- Connect Facebook Page wizard (Messenger)
- Connect WhatsApp wizard (new number or keep WhatsApp Business app)
- test-message step that confirms the channel works
- channel health status, reconnect, disconnect
- assisted setup support + platform admin view of setup progress and errors

### Multi-tenancy

- tenant isolation
- tenant users
- roles

### SaaS Subscriptions (see §42)

- packages (plans) with prices per billing cycle and feature limits
- each tenant has a subscription: package, price, status, start date, expiry date
- statuses: TRIAL, ACTIVE, GRACE, EXPIRED, SUSPENDED, CANCELLED
- daily job updates statuses; access enforced in the backend (expired = read-only)
- plan limits enforced (users, channels, etc.)
- manual subscription payment recording + receipt
- manual renewal, upgrade/downgrade
- expiry reminder emails and in-app banner
- tenant "Subscription" settings page

### Platform Admin Console

- platform users and roles (separate from tenant users)
- create and set up tenant accounts
- assign package, set dates, record subscription payments
- suspend / reactivate / cancel tenants
- manage packages, prices and limits
- expiring / expired subscriptions list
- basic platform metrics (active tenants, MRR, renewals due)

### Channels

- WhatsApp (official Cloud API, including outbound replies within the 24-hour customer service window)
- Messenger (Facebook Page connection)
- Generic channel adapter interface so TikTok/Instagram can be added later
- **No TikTok in MVP**

### Unified Inbox

- inbound messages
- outbound replies
- conversations
- real-time updates (WebSocket or SSE)
- customer identification
- message history
- filters: All, Unread, WhatsApp, Messenger, Has order, Payment pending, Delivery pending, Assigned to me

### Customer

- customer profile
- duplicate detection (suggest only; merge requires an authorized user)
- customer timeline across WhatsApp and Messenger

### Products

- product catalogue
- price
- inventory quantity

### Orders

- create from conversation (pre-filled customer, conversation, channel)
- create manually (phone / walk-in orders)
- source channel and optional lead source (e.g. "saw it on TikTok")
- order status
- order history

### Invoice

- invoice creation from order
- invoice PDF
- payment status derived from recorded payments

### Delivery (manual record-keeping)

- delivery record per order
- delivery method: own staff / courier (name as free text) / customer pickup
- optional tracking reference
- status updated manually by staff
- delivered date/time and who updated it
- full status history

### Payment (manual record-keeping)

- record payment received against an invoice/order
- amount, method (cash, COD, eSewa, Khalti, Fonepay, bank transfer, cheque, other), reference, date
- partial payments supported
- void-and-re-enter for corrections (no silent edits)
- outstanding and overdue amounts calculated automatically

### Dashboard

- messages (by channel)
- orders (by channel, by status)
- sales (daily / weekly / monthly)
- pending payments and overdue amounts
- pending / delivered deliveries
- revenue by source channel and lead source

### Mobile

- responsive, mobile-first web UI
- installable PWA (push notifications for new messages may follow shortly after MVP)

### Security

- RBAC
- audit log
- webhook signature verification
- encrypted credentials
- rate limiting
- tenant isolation

---

# 47. DO NOT BUILD IN MVP

Avoid:

- full accounting system
- payroll
- complicated procurement
- advanced warehouse management
- AI autonomous agent
- complicated marketing automation
- dozens of payment gateways
- dozens of social platforms
- native mobile apps
- TikTok integration (any capability)
- Instagram integration (first candidate channel after MVP)
- any payment gateway integration (eSewa, Khalti, Fonepay, cards) — payments are recorded manually
- courier/logistics API integration — deliveries are recorded manually
- automated COD reconciliation with couriers
- quotations (post-MVP; add if B2B tenants need them)
- AI features (intent detection, product matching, order extraction, suggested replies)
- automated outbound follow-ups / WhatsApp template campaigns
- online/automatic subscription billing (card or gateway auto-charge) — subscriptions are in MVP, but payments are recorded manually
- public self-service sign-up

Build the foundation correctly first.

---

# 48. TESTING REQUIREMENTS

Production-grade means tests are mandatory.

Implement:

### Unit tests

- services
- repositories
- identity matching
- order calculations
- invoice calculations
- permission checks

### Integration tests

- PostgreSQL
- Redis
- webhook processing
- provider adapters

### Security tests

- cross-tenant access
- unauthorized access
- IDOR
- privilege escalation
- token exposure
- webhook forgery
- replay attacks
- rate limiting
- expired/suspended tenant cannot perform write actions
- plan limits cannot be bypassed via API
- tenant users cannot access the Platform Admin Console

### E2E

Test:

```text
Platform admin creates tenant + subscription
→ Owner accepts invite
→ Connect channel
→ Receive message
→ Identify customer
→ Create order
→ Invoice
→ Record delivery
→ Record payment
→ Verify dashboard + customer history
```

Use Playwright for frontend E2E.

---

# 49. PERFORMANCE TARGETS

Design for:

- 1,000+ tenants initially
- 100,000+ customers
- millions of messages
- asynchronous webhook processing
- horizontal backend scaling

Do not optimize prematurely, but do not build a single-process architecture.

All external integrations must be asynchronous where appropriate.

---

# 50. DOCKER

Create:

```text
docker-compose.yml
docker-compose.dev.yml
docker-compose.prod.yml
```

Services:

```text
frontend
backend
postgres
redis
worker
beat
nginx
```

Use `.env.example`.

Never commit `.env`.

---

# 51. ENVIRONMENT VARIABLES

Example:

```env
APP_ENV=development

DATABASE_URL=
REDIS_URL=

JWT_SECRET=
ENCRYPTION_KEY=

CORS_ORIGINS=

# One Meta app serves WhatsApp and Messenger — see docs/ONBOARDING_AND_CHANNEL_SETUP.md §2
WHATSAPP_APP_ID=
WHATSAPP_APP_SECRET=
WHATSAPP_VERIFY_TOKEN=

META_APP_ID=
META_APP_SECRET=

# TikTok — post-MVP
TIKTOK_CLIENT_KEY=
TIKTOK_CLIENT_SECRET=
TIKTOK_REDIRECT_URI=

S3_ENDPOINT=
S3_ACCESS_KEY=
S3_SECRET_KEY=
S3_BUCKET=

AI_PROVIDER=
AI_API_KEY=

SENTRY_DSN=
```

Secrets must never be committed.

---

# 52. DOCUMENTATION

Create:

```text
README.md
ARCHITECTURE.md
SECURITY.md
DATABASE.md
API.md
DEVELOPMENT.md
DEPLOYMENT.md
INTEGRATIONS.md
WHATSAPP_SETUP.md
MESSENGER_SETUP.md
TIKTOK_SETUP.md        (post-MVP)
AI_ARCHITECTURE.md
TESTING.md
```

README must include:

- project overview
- architecture
- prerequisites
- local setup
- environment variables
- database setup
- migrations
- Docker
- running backend
- running frontend
- running worker
- social API setup
- webhook setup
- production deployment
- security
- testing
- troubleshooting

---

# 53. IMPORTANT DEVELOPMENT RULES

Do not generate a toy/demo application.

Do not use:

- fake APIs
- hard-coded tenant IDs
- hard-coded users
- fake authentication
- plaintext access tokens
- mock social APIs in production code
- localStorage JWTs without a strong security reason
- sequential public IDs

Use real provider adapters with clean interfaces.

Where an external API requires credentials or approval that are not yet available, implement the adapter interface, configuration, validation and integration tests using controlled mocks—but clearly mark the exact production configuration required.

---

# 54. DEVELOPMENT PROCESS

Build in phases.

## Phase 0 (starts immediately, runs in parallel with all phases)

Meta approvals — **the longest lead-time item; real SMEs cannot connect without it.** See `docs/ONBOARDING_AND_CHANNEL_SETUP.md` §2:

- Meta Business portfolio + business verification for our company
- Meta app (Messenger, WhatsApp, Facebook Login for Business)
- privacy policy, terms, data deletion URL
- App Review for advanced permissions
- WhatsApp Tech Provider + Embedded Signup

## Phase 1

Foundation:

- monorepo
- Docker
- FastAPI
- Next.js
- PostgreSQL
- Redis
- migrations
- authentication
- tenant architecture
- RBAC
- audit logging
- platform users + Platform Admin Console (tenant setup)
- plans, prices, features, subscriptions, status job, entitlement checks
- manual subscription payments, renewal, expiry reminders

## Phase 2

Customer + Inbox:

- customer
- identities
- conversations
- messages
- unified inbox
- webhook framework

## Phase 3

Facebook Messenger (built first — simpler approval path; see `docs/ONBOARDING_AND_CHANNEL_SETUP.md` §14):

- Connect Facebook Page wizard (Facebook Login for Business)
- Page subscription + webhook
- inbound / outbound messages, message status
- identity resolution
- deauthorize + data deletion callbacks
- channel health, reconnect, disconnect

## Phase 4

WhatsApp:

- Connect WhatsApp wizard (Embedded Signup: new number + coexistence)
- number registration, display-name status
- webhook
- inbound message
- outbound message
- message status
- identity resolution
- channel health, reconnect, disconnect

## Phase 5

Sales:

- products
- inventory quantity
- order from conversation / manual order
- source channel + lead source
- invoice + invoice PDF

## Phase 6

Delivery + Payment records (manual):

- delivery records and manual status updates
- delivery status history
- manual payment recording (partial payments, void-and-re-enter)
- derived invoice payment status, outstanding and overdue

## Phase 7

Dashboard:

- messages, orders, sales
- pending payments / overdue
- deliveries
- revenue by channel and lead source

## Phase 8

Production hardening → **MVP release**:

- security testing
- performance testing
- monitoring
- backups
- disaster recovery
- deployment documentation

---

## Post-MVP (in suggested order, driven by pilot-customer feedback)

1. Instagram DMs (reuses Meta OAuth/webhook infrastructure)
2. PWA push notifications, WhatsApp template messages and follow-up tasks
3. Quotations (if B2B tenants need them)
4. Payment gateways (eSewa, Khalti, Fonepay) behind `PaymentProvider`
5. Courier integrations and COD reconciliation
6. AI: intent detection, product matching, order extraction, suggested replies
7. TikTok (only approved capabilities, behind feature flags)
8. Self-service sign-up and online subscription payment / auto-renewal

---

# 55. REQUIRED FINAL DELIVERABLE

At completion provide:

1. Complete source code
2. Docker configuration
3. Database migrations
4. Seed data
5. `.env.example`
6. API documentation
7. README
8. Architecture documentation
9. Security documentation
10. Social API setup documentation
11. Automated tests
12. Production deployment documentation
13. Backup/restore documentation
14. CI/CD configuration
15. Health checks
16. Logging/monitoring configuration

The application must run from a clean machine using the documented setup.

Do not consider the project complete until:

```text
docker compose up
```

or the documented production process successfully starts all required services.

---

# 56. FIRST IMPLEMENTATION TASK

Before writing application features:

1. Analyze the entire specification.
2. Create `ARCHITECTURE.md`.
3. Create database ERD/documentation.
4. Create repository structure.
5. Create Docker infrastructure.
6. Create FastAPI application.
7. Create Next.js application.
8. Create PostgreSQL migrations.
9. Implement tenant/auth/RBAC foundation, platform admin and subscriptions/entitlements.
10. Implement security middleware.
11. Implement webhook framework.
12. Then proceed module by module.

Do not build everything in one generated response.

Work incrementally.

After each major phase:

- run tests
- run migrations
- verify Docker
- verify API
- verify frontend
- update documentation
- report completed items and remaining items

The final application must be maintainable by a professional development team.

# END OF SPECIFICATION
