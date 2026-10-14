import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.api.base_field_config.crud import (
    base_field_configs_crud,
    ensure_base_field_update_allowed,
)
from app.api.base_field_config.schemas import (
    BaseFieldConfigPublic,
    BaseFieldConfigUpdate,
)
from app.api.popup.guards import CallerToken
from app.core.dependencies.users import CurrentWriter, TenantSession

router = APIRouter(prefix="/base-field-configs", tags=["base-field-configs"])


@router.get("", response_model=list[BaseFieldConfigPublic])
async def list_base_field_configs(
    db: TenantSession,
    _: CurrentWriter,
    popup_id: uuid.UUID = Query(..., description="Filter by popup ID"),
) -> list[BaseFieldConfigPublic]:
    configs = base_field_configs_crud.find_by_popup(db, popup_id)
    return [BaseFieldConfigPublic.model_validate(c) for c in configs]


@router.patch("/{config_id}", response_model=BaseFieldConfigPublic)
async def update_base_field_config(
    config_id: uuid.UUID,
    config_in: BaseFieldConfigUpdate,
    db: TenantSession,
    current_user: CurrentWriter,
    token_payload: CallerToken,
) -> BaseFieldConfigPublic:
    config = base_field_configs_crud.get(db, config_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Base field config not found",
        )

    update_data = config_in.model_dump(exclude_unset=True)
    ensure_base_field_update_allowed(config, update_data)

    if "section_id" in update_data and config.section_id != update_data["section_id"]:
        from app.api.audit_log.actor import actor_from_user_or_api_key
        from app.api.audit_log.constants import AuditAction, AuditEntityType
        from app.api.audit_log.crud import audit_logs_crud

        new_section_id = update_data["section_id"]
        audit_logs_crud.record(
            db,
            tenant_id=config.tenant_id,
            actor=actor_from_user_or_api_key(
                current_user, api_key_id=token_payload.api_key_id
            ),
            action=AuditAction.FORM_FIELD_SECTION_CHANGED,
            entity_type=AuditEntityType.BASE_FIELD_CONFIG,
            entity_id=config.id,
            entity_label=config.field_name,
            popup_id=config.popup_id,
            details={
                "sales_flow_id": str(config.sales_flow_id),
                "field_kind": "base",
                "field_name": config.field_name,
                "previous_section_id": (
                    str(config.section_id) if config.section_id else None
                ),
                "section_id": str(new_section_id) if new_section_id else None,
                "auth": {
                    "via_api_key": token_payload.via_api_key,
                    "api_key_id": token_payload.api_key_id,
                },
            },
        )

    updated = base_field_configs_crud.update(db, config, config_in)
    return BaseFieldConfigPublic.model_validate(updated)
