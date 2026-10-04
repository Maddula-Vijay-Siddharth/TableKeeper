# TableKeeper

TableKeeper is an AI-built restaurant reservation system developed for the
WeAreDevelopers × BAND AI Dark Factory Hackathon.

The system allows customers to discover restaurants, check table
availability, create reservations, view reservations, and cancel bookings.
Restaurant staff can manage tables and service availability.

## Core Goal

The most important requirement is:

> A restaurant table must never be double-booked for overlapping
> reservation times, even when multiple requests arrive concurrently.

TableKeeper uses PostgreSQL database-level constraints and transactions
to enforce this invariant.

## Features

- Restaurant discovery
- Restaurant and table availability
- Reservation creation
- Reservation lookup
- Reservation cancellation
- Restaurant table management
- Service-period management
- Timezone-aware reservations
- DST validation
- Idempotent reservation requests
- Transactional reservation handling
- PostgreSQL concurrency protection
- Stable API error responses
- Automated tests

## Architecture

The project is developed using an AI software factory coordinated through
BAND.

```text
Requirements
     |
     v
Architecture Agent
     |
     v
Implementation Agent
     |
     v
Verification / Test Agent
     |
     +------ FAIL ------> Implementation Agent
     |
     v
Review Agent
     |
     v
Final Acceptance
