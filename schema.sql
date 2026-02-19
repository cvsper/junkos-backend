-- ============================================================================
-- Umuve -- PostgreSQL Schema
-- On-demand junk removal marketplace
-- ============================================================================
-- Run with: psql -U <user> -d umuve -f schema.sql
-- ============================================================================

BEGIN;

-- --------------------------------------------------------------------------
-- Extensions
-- --------------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";   -- uuid_generate_v4()
CREATE EXTENSION IF NOT EXISTS "postgis";     -- geospatial queries (nearby drivers)

-- --------------------------------------------------------------------------
-- Custom enum types
-- --------------------------------------------------------------------------

CREATE TYPE user_role AS ENUM (
    'customer',
    'driver',
    'admin'
);

CREATE TYPE job_status AS ENUM (
    'pending',
    'confirmed',
    'assigned',
    'en_route',
    'arrived',
    'in_progress',
    'completed',
    'cancelled'
);

CREATE TYPE contractor_status AS ENUM (
    'pending',
    'approved',
    'suspended',
    'rejected'
);

CREATE TYPE payout_status AS ENUM (
    'pending',
    'processing',
    'completed',
    'failed'
);

CREATE TYPE payment_status AS ENUM (
    'pending',
    'authorized',
    'captured',
    'refunded',
    'failed'
);

-- --------------------------------------------------------------------------
-- 1. users
-- Core user accounts for customers, drivers, and admins.
-- --------------------------------------------------------------------------

CREATE TABLE users (
    id                 UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
    email              VARCHAR(255) NOT NULL,
    phone              VARCHAR(20)  NOT NULL,
    name               VARCHAR(255) NOT NULL,
    password_hash      TEXT         NOT NULL,
    role               user_role    NOT NULL DEFAULT 'customer',
    avatar_url         TEXT,
    stripe_customer_id VARCHAR(255),
    status             VARCHAR(20)  NOT NULL DEFAULT 'active'
                           CHECK (status IN ('active', 'suspended')),
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Unique constraints (also serve as indexes for lookups)
CREATE UNIQUE INDEX idx_users_email ON users (email);
CREATE UNIQUE INDEX idx_users_phone ON users (phone);

-- --------------------------------------------------------------------------
-- 2. contractors
-- Extended profile for users with the driver role.  Tracks vehicle info,
-- real-time location, approval status, and Stripe Connect payouts.
-- --------------------------------------------------------------------------

CREATE TABLE contractors (
    id                    UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id               UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    license_url           TEXT,
    insurance_url         TEXT,
    truck_photos          JSONB       DEFAULT '[]'::jsonb,
    truck_type            VARCHAR(100),
    truck_capacity        VARCHAR(50),
    stripe_connect_id     VARCHAR(255),
    is_online             BOOLEAN     NOT NULL DEFAULT FALSE,
    current_lat           DECIMAL(10, 7),
    current_lng           DECIMAL(10, 7),
    avg_rating            DECIMAL(3, 2) NOT NULL DEFAULT 0.00
                              CHECK (avg_rating >= 0 AND avg_rating <= 5),
    total_jobs            INTEGER     NOT NULL DEFAULT 0,
    approval_status       contractor_status NOT NULL DEFAULT 'pending',
    availability_schedule JSONB       DEFAULT '{}'::jsonb,
    approved_at           TIMESTAMPTZ,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- One contractor profile per user
CREATE UNIQUE INDEX idx_contractors_user_id       ON contractors (user_id);

-- Dispatch lookups: online and approved drivers
CREATE INDEX idx_contractors_is_online            ON contractors (is_online) WHERE is_online = TRUE;
CREATE INDEX idx_contractors_approval_status      ON contractors (approval_status);

-- B-tree coordinate index for coarse nearby-driver filtering
CREATE INDEX idx_contractors_location ON contractors (current_lat, current_lng)
    WHERE current_lat IS NOT NULL AND current_lng IS NOT NULL;

-- PostGIS spatial index for precise radius queries on contractor location.
--
-- Example usage:
--   SELECT c.*, u.name, u.phone
--   FROM contractors c
--   JOIN users u ON u.id = c.user_id
--   WHERE c.is_online = TRUE
--     AND c.approval_status = 'approved'
--     AND ST_DWithin(
--           ST_SetSRID(ST_MakePoint(c.current_lng, c.current_lat), 4326)::geography,
--           ST_SetSRID(ST_MakePoint(:job_lng, :job_lat), 4326)::geography,
--           :radius_meters
--         )
--   ORDER BY ST_Distance(
--       ST_SetSRID(ST_MakePoint(c.current_lng, c.current_lat), 4326)::geography,
--       ST_SetSRID(ST_MakePoint(:job_lng, :job_lat), 4326)::geography
--   )
--   LIMIT 10;
CREATE INDEX idx_contractors_geo ON contractors
    USING GIST (
        ST_SetSRID(ST_MakePoint(
            COALESCE(current_lng, 0),
            COALESCE(current_lat, 0)
        ), 4326)::geography
    );

-- --------------------------------------------------------------------------
-- 3. jobs
-- Central table for pickup requests.  Tracks the full lifecycle from booking
-- through completion, including itemized pricing and driver payouts.
-- --------------------------------------------------------------------------

CREATE TABLE jobs (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id         UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    driver_id           UUID        REFERENCES contractors(id) ON DELETE SET NULL,

    status              job_status  NOT NULL DEFAULT 'pending',

    -- Pickup location
    address             TEXT        NOT NULL,
    lat                 DECIMAL(10, 7),
    lng                 DECIMAL(10, 7),

    -- Items and media
    items               JSONB       DEFAULT '[]'::jsonb,   -- [{type, qty, price}, ...]
    volume_estimate     VARCHAR(50),
    photos              JSONB       DEFAULT '[]'::jsonb,   -- customer-uploaded photos
    before_photos       JSONB       DEFAULT '[]'::jsonb,   -- driver before-pickup photos
    after_photos        JSONB       DEFAULT '[]'::jsonb,   -- driver after-pickup photos

    -- Lifecycle timestamps
    scheduled_at        TIMESTAMPTZ,
    accepted_at         TIMESTAMPTZ,
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    cancelled_at        TIMESTAMPTZ,
    cancellation_reason TEXT,

    -- Pricing breakdown
    price_items         DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    price_volume_adj    DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    price_surge         DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    price_service_fee   DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    price_total         DECIMAL(10, 2) NOT NULL DEFAULT 0.00,

    -- Payout splits
    driver_payout       DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    platform_commission DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    surge_multiplier    DECIMAL(4, 2)  NOT NULL DEFAULT 1.00,

    notes               TEXT,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_jobs_customer_id  ON jobs (customer_id);
CREATE INDEX idx_jobs_driver_id    ON jobs (driver_id);
CREATE INDEX idx_jobs_status       ON jobs (status);
CREATE INDEX idx_jobs_scheduled_at ON jobs (scheduled_at);
CREATE INDEX idx_jobs_created_at   ON jobs (created_at);

-- --------------------------------------------------------------------------
-- 4. ratings
-- Bidirectional ratings: customer rates driver and driver rates customer.
-- --------------------------------------------------------------------------

CREATE TABLE ratings (
    id           UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id       UUID        NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    from_user_id UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    to_user_id   UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stars        SMALLINT    NOT NULL CHECK (stars >= 1 AND stars <= 5),
    comment      TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ratings_job_id     ON ratings (job_id);
CREATE INDEX idx_ratings_to_user_id ON ratings (to_user_id);

-- --------------------------------------------------------------------------
-- 5. payments
-- Stripe payment intents linked to jobs, with payout tracking.
-- --------------------------------------------------------------------------

CREATE TABLE payments (
    id                       UUID           PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id                   UUID           NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    stripe_payment_intent_id VARCHAR(255),
    amount                   DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    service_fee              DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    commission               DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    driver_payout_amount     DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    payout_status            payout_status  NOT NULL DEFAULT 'pending',
    payment_status           payment_status NOT NULL DEFAULT 'pending',
    tip_amount               DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    refund_amount            DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    created_at               TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_payments_job_id                   ON payments (job_id);
CREATE INDEX idx_payments_stripe_payment_intent_id ON payments (stripe_payment_intent_id);

-- --------------------------------------------------------------------------
-- 6. pricing_rules
-- Configurable per-item and per-volume pricing used by the estimation engine.
-- --------------------------------------------------------------------------

CREATE TABLE pricing_rules (
    id          UUID           PRIMARY KEY DEFAULT uuid_generate_v4(),
    item_type   VARCHAR(100)   NOT NULL,
    base_price  DECIMAL(10, 2) NOT NULL,
    description TEXT,
    is_active   BOOLEAN        NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

-- --------------------------------------------------------------------------
-- 7. surge_zones
-- Geographic zones with time-based surge multipliers.
-- boundary stores GeoJSON-style polygon coordinates as JSONB.
-- --------------------------------------------------------------------------

CREATE TABLE surge_zones (
    id               UUID           PRIMARY KEY DEFAULT uuid_generate_v4(),
    name             VARCHAR(255)   NOT NULL,
    boundary         JSONB          NOT NULL DEFAULT '[]'::jsonb,
    surge_multiplier DECIMAL(4, 2)  NOT NULL DEFAULT 1.00,
    is_active        BOOLEAN        NOT NULL DEFAULT TRUE,
    start_time       TIME,
    end_time         TIME,
    days_of_week     INTEGER[]      DEFAULT '{}',  -- 0 = Sunday ... 6 = Saturday
    created_at       TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

-- --------------------------------------------------------------------------
-- 8. notifications
-- Push and in-app notifications for all user types.
-- --------------------------------------------------------------------------

CREATE TABLE notifications (
    id         UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id    UUID         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type       VARCHAR(50)  NOT NULL,    -- e.g. 'job_assigned', 'payment_received'
    title      VARCHAR(255) NOT NULL,
    body       TEXT,
    data       JSONB        DEFAULT '{}'::jsonb,
    is_read    BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_notifications_user_id ON notifications (user_id);
CREATE INDEX idx_notifications_is_read ON notifications (user_id, is_read);

-- --------------------------------------------------------------------------
-- 9. contractor_documents
-- Uploaded verification documents (license, insurance, certifications).
-- --------------------------------------------------------------------------

CREATE TABLE contractor_documents (
    id            UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    contractor_id UUID        NOT NULL REFERENCES contractors(id) ON DELETE CASCADE,
    document_type VARCHAR(50) NOT NULL,   -- e.g. 'drivers_license', 'insurance', 'certification'
    document_url  TEXT        NOT NULL,
    verified      BOOLEAN     NOT NULL DEFAULT FALSE,
    verified_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_contractor_documents_contractor_id ON contractor_documents (contractor_id);

-- --------------------------------------------------------------------------
-- Trigger function: automatically set updated_at on row modification
-- --------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $trigger$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$trigger$ LANGUAGE plpgsql;

-- Apply the trigger to every table that has an updated_at column

CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_contractors_updated_at
    BEFORE UPDATE ON contractors
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_jobs_updated_at
    BEFORE UPDATE ON jobs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_payments_updated_at
    BEFORE UPDATE ON payments
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_pricing_rules_updated_at
    BEFORE UPDATE ON pricing_rules
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_surge_zones_updated_at
    BEFORE UPDATE ON surge_zones
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================================
-- Seed data: common junk removal pricing
-- ============================================================================

INSERT INTO pricing_rules (item_type, base_price, description) VALUES
    -- Furniture
    ('couch_sofa',               75.00, 'Standard couch or sofa removal'),
    ('mattress',                 50.00, 'Mattress of any size (twin through king)'),
    ('desk_table',               60.00, 'Desk, dining table, or similar furniture'),
    ('chair',                    30.00, 'Office chair, recliner, or accent chair'),

    -- Appliances
    ('refrigerator',            100.00, 'Refrigerator or freezer (Freon-safe disposal)'),
    ('washer_dryer',             85.00, 'Washing machine or dryer unit'),
    ('tv_monitor',               35.00, 'Television or computer monitor (e-waste recycling)'),

    -- Volume-based pricing
    ('yard_debris_cuyd',         45.00, 'Yard debris priced per cubic yard'),
    ('construction_debris_cuyd', 65.00, 'Construction / renovation debris per cubic yard'),
    ('general_junk_cuyd',        40.00, 'General household junk per cubic yard'),

    -- Truck-load packages
    ('full_truck_load',         450.00, 'Full truck load (~16 cubic yards)'),
    ('half_truck_load',         275.00, 'Half truck load (~8 cubic yards)'),
    ('quarter_truck_load',      175.00, 'Quarter truck load (~4 cubic yards)'),

    -- Minimum charge
    ('minimum_pickup',           99.00, 'Minimum pickup fee for small jobs');

COMMIT;
