# API Contract (v1 draft)

## Auth
- POST /v1/auth/register
- POST /v1/auth/login
- POST /v1/auth/refresh

## Profile
- GET /v1/profile/me
- PUT /v1/profile/me

## Letters
- POST /v1/letters
- GET /v1/letters/inbox
- GET /v1/letters/outbox
- GET /v1/letters/{id}
- POST /v1/letters/{id}/read
- POST /v1/letters/{id}/reply

## Discovery/Matching
- GET /v1/discovery/candidates
- POST /v1/discovery/search
- POST /v1/matching/auto

## Safety
- POST /v1/reports
- POST /v1/blocks
- DELETE /v1/blocks/{userId}
