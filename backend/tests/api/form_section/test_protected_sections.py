import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.api.popup.models import Popups
from app.api.sales_flow.crud import sales_flows_crud
from app.api.tenant.models import Tenants
from tests._flow_helpers import default_flow_id


def test_protected_section_cannot_be_deleted_until_unprotected(
    client: TestClient,
    db: Session,
    tenant_a: Tenants,
    admin_token_tenant_a: str,
) -> None:
    slug = f"protected-section-{uuid.uuid4().hex[:8]}"
    popup = Popups(tenant_id=tenant_a.id, name=f"Popup {slug}", slug=slug)
    db.add(popup)
    db.flush()
    sales_flows_crud.provision_default_flow(
        db, popup_id=popup.id, tenant_id=tenant_a.id, sale_type="application"
    )
    flow_id = default_flow_id(db, popup.id)
    db.commit()
    headers = {"Authorization": f"Bearer {admin_token_tenant_a}"}

    created = client.post(
        "/api/v1/form-sections",
        headers=headers,
        json={
            "popup_id": str(popup.id),
            "sales_flow_id": str(flow_id),
            "label": "Personal Information",
            "protected": True,
        },
    )
    assert created.status_code == 201, created.text
    section_id = created.json()["id"]
    assert created.json()["protected"] is True

    deleted = client.delete(f"/api/v1/form-sections/{section_id}", headers=headers)
    assert deleted.status_code == 400
    assert deleted.json()["detail"] == "Cannot delete a protected section"

    updated = client.patch(
        f"/api/v1/form-sections/{section_id}",
        headers=headers,
        json={"protected": False},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["protected"] is False

    deleted = client.delete(f"/api/v1/form-sections/{section_id}", headers=headers)
    assert deleted.status_code == 204
