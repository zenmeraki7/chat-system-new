# Database Schema (v1)

Core tables:
- users
- profiles
- interests
- user_interests
- languages
- user_languages
- countries_regions
- letters
- letter_recipients
- letter_delivery_jobs
- penpal_connections
- reports
- blocks
- moderation_actions
- notifications
- subscriptions
- purchases
- devices
- sessions
- audit_logs

Delivery guarantees:
- unique(letter_delivery_jobs.idempotency_key)
- index(letter_delivery_jobs.not_before, letter_delivery_jobs.job_state)
- index(letter_recipients.recipient_id, letter_recipients.state)
