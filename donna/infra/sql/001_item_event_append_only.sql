-- Defense in depth for the append-only ledger: the application layer
-- already refuses UPDATE/DELETE on item_event; this trigger makes the
-- database refuse too. Run once against the donna database after the
-- first deployment has created the schema.

CREATE OR REPLACE FUNCTION item_event_append_only()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'item_event is append-only (no % allowed)', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_item_event_append_only ON item_event;

CREATE TRIGGER trg_item_event_append_only
    BEFORE UPDATE OR DELETE ON item_event
    FOR EACH ROW EXECUTE FUNCTION item_event_append_only();

-- Grant the managed identity (Entra principal, created via
-- `select * from pgaadauth_create_principal('<mi-name>', false, false)`)
-- the minimum it needs.
-- GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO "<mi-name>";
-- REVOKE UPDATE, DELETE ON item_event FROM "<mi-name>";
