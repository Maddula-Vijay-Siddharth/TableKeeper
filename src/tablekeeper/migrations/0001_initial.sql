CREATE EXTENSION IF NOT EXISTS btree_gist;

DO $$ BEGIN
    CREATE TYPE reservationstatus AS ENUM ('confirmed', 'cancelled');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE idempotencystate AS ENUM ('in_progress', 'completed');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE membershiprole AS ENUM ('owner', 'manager', 'staff');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS users (
    id uuid PRIMARY KEY,
    email varchar(320) NOT NULL UNIQUE,
    name varchar(200) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS restaurants (
    id uuid PRIMARY KEY,
    name varchar(200) NOT NULL,
    slug varchar(120) NOT NULL UNIQUE,
    location varchar(240) NOT NULL,
    timezone varchar(80) NOT NULL,
    published boolean NOT NULL DEFAULT false,
    default_duration_minutes integer NOT NULL DEFAULT 90,
    buffer_minutes integer NOT NULL DEFAULT 15,
    lead_time_minutes integer NOT NULL DEFAULT 60,
    horizon_days integer NOT NULL DEFAULT 60,
    min_party_size integer NOT NULL DEFAULT 1,
    max_party_size integer NOT NULL DEFAULT 12,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_restaurant_default_duration_positive CHECK (default_duration_minutes > 0),
    CONSTRAINT ck_restaurant_buffer_nonnegative CHECK (buffer_minutes >= 0),
    CONSTRAINT ck_restaurant_lead_nonnegative CHECK (lead_time_minutes >= 0),
    CONSTRAINT ck_restaurant_horizon_positive CHECK (horizon_days > 0),
    CONSTRAINT ck_restaurant_party_bounds CHECK (min_party_size > 0 AND max_party_size >= min_party_size)
);

CREATE TABLE IF NOT EXISTS restaurant_memberships (
    id uuid PRIMARY KEY,
    restaurant_id uuid NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role membershiprole NOT NULL DEFAULT 'owner',
    CONSTRAINT uq_membership_restaurant_user UNIQUE (restaurant_id, user_id)
);

CREATE TABLE IF NOT EXISTS tables (
    id uuid PRIMARY KEY,
    restaurant_id uuid NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
    label varchar(80) NOT NULL,
    capacity integer NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_table_restaurant_label UNIQUE (restaurant_id, label),
    CONSTRAINT ck_table_capacity_positive CHECK (capacity > 0)
);

CREATE INDEX IF NOT EXISTS ix_tables_restaurant_enabled_capacity ON tables(restaurant_id, enabled, capacity);

CREATE TABLE IF NOT EXISTS service_periods (
    id uuid PRIMARY KEY,
    restaurant_id uuid NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
    weekday integer,
    service_date date,
    opens_at time NOT NULL,
    closes_at time NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    CONSTRAINT ck_period_weekday_xor_date CHECK ((weekday IS NOT NULL) <> (service_date IS NOT NULL)),
    CONSTRAINT ck_period_weekday_range CHECK (weekday IS NULL OR (weekday >= 0 AND weekday <= 6))
);

CREATE INDEX IF NOT EXISTS ix_service_periods_restaurant_date ON service_periods(restaurant_id, service_date);

CREATE TABLE IF NOT EXISTS reservations (
    id uuid PRIMARY KEY,
    restaurant_id uuid NOT NULL REFERENCES restaurants(id) ON DELETE RESTRICT,
    customer_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    status reservationstatus NOT NULL DEFAULT 'confirmed',
    party_size integer NOT NULL,
    requested_local_date date NOT NULL,
    requested_local_time time NOT NULL,
    timezone varchar(80) NOT NULL,
    starts_at timestamptz NOT NULL,
    ends_at timestamptz NOT NULL,
    idempotency_key varchar(200) NOT NULL,
    cancelled_at timestamptz,
    cancellation_reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_reservation_party_positive CHECK (party_size > 0),
    CONSTRAINT ck_reservation_end_after_start CHECK (ends_at > starts_at)
);

CREATE INDEX IF NOT EXISTS ix_reservations_customer_start ON reservations(customer_id, starts_at);
CREATE INDEX IF NOT EXISTS ix_reservations_restaurant_start ON reservations(restaurant_id, starts_at);

CREATE TABLE IF NOT EXISTS reservation_tables (
    id uuid PRIMARY KEY,
    reservation_id uuid NOT NULL REFERENCES reservations(id) ON DELETE CASCADE,
    table_id uuid NOT NULL REFERENCES tables(id) ON DELETE RESTRICT,
    occupied_range tstzrange NOT NULL,
    blocks_inventory boolean NOT NULL DEFAULT true,
    CONSTRAINT ck_occupied_range_nonempty CHECK (NOT isempty(occupied_range))
);

CREATE INDEX IF NOT EXISTS ix_reservation_tables_table ON reservation_tables(table_id);

DO $$ BEGIN
    ALTER TABLE reservation_tables
        ADD CONSTRAINT excl_reservation_table_overlap
        EXCLUDE USING gist (table_id WITH =, occupied_range WITH &&)
        WHERE (blocks_inventory);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS idempotency_records (
    id uuid PRIMARY KEY,
    principal_id uuid NOT NULL,
    key varchar(200) NOT NULL,
    request_hash varchar(64) NOT NULL,
    state idempotencystate NOT NULL DEFAULT 'in_progress',
    response_status integer,
    response_body jsonb,
    reservation_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    CONSTRAINT uq_idempotency_principal_key UNIQUE (principal_id, key)
);

CREATE TABLE IF NOT EXISTS outbox_events (
    id uuid PRIMARY KEY,
    event_type varchar(120) NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    delivered_at timestamptz
);
