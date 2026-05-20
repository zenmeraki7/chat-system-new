# PenPal Slow Letter App Blueprint

This document is the implementation baseline for a React Native CLI (no Expo) global slow-letter app.

## Product pillars
- Slow by design
- Safety by default
- Depth over volume
- Collectible identity

## Core backend modules
- auth
- profile
- discovery
- matching
- letters
- delayed_delivery
- moderation
- stamps
- subscriptions
- notifications

## Delivery states
`draft -> queued -> in_transit -> delivered -> read -> replied`
Exception states: `blocked`, `failed`

## Queue guarantees
- idempotency key per recipient delivery
- Redis lock + DB transaction boundary
- exponential retry with dead-letter queue

## Privacy
- country/region-level location only
- no exact coordinates exposed
- consent gate for media/audio

## Initial SLO targets
- API p95 < 350ms
- delivery job success >= 99.9%
- duplicate delivery = 0
- notification success >= 98.5%
