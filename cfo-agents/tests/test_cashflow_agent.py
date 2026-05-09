from app.agents.orchestrator import Orchestrator
from app.db.models import Forecast


def test_cashflow_creates_three_horizons(db_session):
    Orchestrator().dispatch(db_session, tenant_id="demo", task_type="BUILD_CASHFLOW_FORECAST")
    horizons = sorted(
        f.horizon_days for f in db_session.query(Forecast).filter_by(tenant_id="demo").all()
    )
    assert horizons == [7, 30, 90]
