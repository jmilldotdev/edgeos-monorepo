"""Guards shared by /base-field-configs and /form-fields base-config updates.

Both PATCH routes must enforce the catalog invariants identically:
- non-removable elementals cannot be made optional
- field_type only changes within the catalog's allowed_field_types whitelist
"""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.audit_log.models import AuditLog
from app.api.base_field_config.models import BaseFieldConfigs
from app.api.form_section.models import FormSections
from app.api.popup.models import Popups
from app.api.tenant.models import Tenants
from tests._flow_helpers import default_flow_id, provision_default_flow

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _admin_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _make_popup(db: Session, tenant: Tenants) -> Popups:
    slug = f"bfc-guard-{uuid.uuid4().hex[:8]}"
    popup = Popups(name=f"BFC Guard {slug}", slug=slug, tenant_id=tenant.id)
    db.add(popup)
    db.commit()
    db.refresh(popup)
    provision_default_flow(db, popup)
    return popup


def _make_config(
    db: Session,
    popup: Popups,
    field_name: str,
    *,
    required: bool = True,
) -> BaseFieldConfigs:
    config = BaseFieldConfigs(
        tenant_id=popup.tenant_id,
        popup_id=popup.id,
        sales_flow_id=default_flow_id(db, popup.id),
        field_name=field_name,
        required=required,
        label=field_name.replace("_", " ").title(),
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


# ---------------------------------------------------------------------------
# /base-field-configs PATCH
# ---------------------------------------------------------------------------


class TestBaseFieldConfigPatchGuards:
    def test_section_reassignment_is_audited(
        self,
        client: TestClient,
        db: Session,
        tenant_a: Tenants,
        admin_token_tenant_a: str,
    ) -> None:
        popup = _make_popup(db, tenant_a)
        flow_id = default_flow_id(db, popup.id)
        original_section = FormSections(
            tenant_id=tenant_a.id,
            popup_id=popup.id,
            sales_flow_id=flow_id,
            label="Personal Information",
        )
        next_section = FormSections(
            tenant_id=tenant_a.id,
            popup_id=popup.id,
            sales_flow_id=flow_id,
            label="Professional Details",
        )
        db.add(original_section)
        db.add(next_section)
        db.commit()
        config = _make_config(db, popup, "residence")
        config.section_id = original_section.id
        db.add(config)
        db.commit()

        resp = client.patch(
            f"/api/v1/base-field-configs/{config.id}",
            headers=_admin_headers(admin_token_tenant_a),
            json={"section_id": str(next_section.id)},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["section_id"] == str(next_section.id)

        audit = db.exec(
            select(AuditLog).where(
                AuditLog.action == "form_field.section_changed",
                AuditLog.entity_id == config.id,
            )
        ).one()
        assert audit.entity_type == "base_field_config"
        assert audit.request_id
        assert audit.details is not None
        assert audit.details["previous_section_id"] == str(original_section.id)
        assert audit.details["section_id"] == str(next_section.id)

    def test_non_removable_field_cannot_be_made_optional(
        self,
        client: TestClient,
        db: Session,
        tenant_a: Tenants,
        admin_token_tenant_a: str,
    ) -> None:
        popup = _make_popup(db, tenant_a)
        config = _make_config(db, popup, "first_name")

        resp = client.patch(
            f"/api/v1/base-field-configs/{config.id}",
            headers=_admin_headers(admin_token_tenant_a),
            json={"required": False},
        )
        assert resp.status_code == 400, resp.text
        assert "cannot be made optional" in resp.json()["detail"]

    def test_field_type_override_rejected_without_whitelist(
        self,
        client: TestClient,
        db: Session,
        tenant_a: Tenants,
        admin_token_tenant_a: str,
    ) -> None:
        popup = _make_popup(db, tenant_a)
        config = _make_config(db, popup, "telegram")

        resp = client.patch(
            f"/api/v1/base-field-configs/{config.id}",
            headers=_admin_headers(admin_token_tenant_a),
            json={"field_type": "select"},
        )
        assert resp.status_code == 400, resp.text
        assert "does not allow type overrides" in resp.json()["detail"]

    def test_field_type_outside_whitelist_rejected(
        self,
        client: TestClient,
        db: Session,
        tenant_a: Tenants,
        admin_token_tenant_a: str,
    ) -> None:
        popup = _make_popup(db, tenant_a)
        config = _make_config(db, popup, "residence")

        resp = client.patch(
            f"/api/v1/base-field-configs/{config.id}",
            headers=_admin_headers(admin_token_tenant_a),
            json={"field_type": "textarea"},
        )
        assert resp.status_code == 400, resp.text
        assert "is not allowed" in resp.json()["detail"]

    def test_field_type_inside_whitelist_accepted(
        self,
        client: TestClient,
        db: Session,
        tenant_a: Tenants,
        admin_token_tenant_a: str,
    ) -> None:
        popup = _make_popup(db, tenant_a)
        config = _make_config(db, popup, "residence")

        resp = client.patch(
            f"/api/v1/base-field-configs/{config.id}",
            headers=_admin_headers(admin_token_tenant_a),
            json={"field_type": "country_select"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["field_type"] == "country_select"

    def test_legal_update_still_works(
        self,
        client: TestClient,
        db: Session,
        tenant_a: Tenants,
        admin_token_tenant_a: str,
    ) -> None:
        popup = _make_popup(db, tenant_a)
        config = _make_config(db, popup, "first_name")

        resp = client.patch(
            f"/api/v1/base-field-configs/{config.id}",
            headers=_admin_headers(admin_token_tenant_a),
            json={"label": "Given name", "position": 3},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["label"] == "Given name"
        assert body["position"] == 3


# ---------------------------------------------------------------------------
# /form-fields PATCH keeps enforcing the same guards
# ---------------------------------------------------------------------------


class TestFormFieldsRouteMirrorsGuards:
    def test_non_removable_field_cannot_be_made_optional_via_form_fields(
        self,
        client: TestClient,
        db: Session,
        tenant_a: Tenants,
        admin_token_tenant_a: str,
    ) -> None:
        popup = _make_popup(db, tenant_a)
        config = _make_config(db, popup, "last_name")

        resp = client.patch(
            f"/api/v1/form-fields/{config.id}",
            headers=_admin_headers(admin_token_tenant_a),
            json={"required": False},
        )
        assert resp.status_code == 400, resp.text
        assert "cannot be made optional" in resp.json()["detail"]

    def test_field_type_outside_whitelist_rejected_via_form_fields(
        self,
        client: TestClient,
        db: Session,
        tenant_a: Tenants,
        admin_token_tenant_a: str,
    ) -> None:
        popup = _make_popup(db, tenant_a)
        config = _make_config(db, popup, "residence")

        resp = client.patch(
            f"/api/v1/form-fields/{config.id}",
            headers=_admin_headers(admin_token_tenant_a),
            json={"field_type": "textarea"},
        )
        assert resp.status_code == 400, resp.text
        assert "is not allowed" in resp.json()["detail"]
