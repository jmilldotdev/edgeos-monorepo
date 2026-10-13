import uuid

from fastapi import APIRouter, HTTPException, status
from loguru import logger
from sqlmodel import Session, func, select

from app.api.base_field_config.models import BaseFieldConfigs
from app.api.form_field.models import FormFields
from app.api.form_section import crud
from app.api.form_section.models import FormSections
from app.api.form_section.schemas import (
    FormSectionCreate,
    FormSectionKind,
    FormSectionPublic,
    FormSectionUpdate,
)
from app.api.popup.guards import CallerToken
from app.api.shared.enums import UserRole
from app.api.shared.response import ListModel, PaginationLimit, PaginationSkip, Paging
from app.api.translation.service import delete_translations_for_entity
from app.core.dependencies.users import (
    AdminOrApiKey_FormsRead,
    AdminOrApiKey_FormsWrite,
    AdminOrApiKeySession_FormsRead,
    AdminOrApiKeySession_FormsWrite,
)
from app.core.logging import get_request_id

router = APIRouter(prefix="/form-sections", tags=["form-sections"])


@router.get("", response_model=ListModel[FormSectionPublic])
async def list_form_sections(
    db: AdminOrApiKeySession_FormsRead,
    _: AdminOrApiKey_FormsRead,
    popup_id: uuid.UUID | None = None,
    sales_flow_id: uuid.UUID | None = None,
    skip: PaginationSkip = 0,
    limit: PaginationLimit = 100,
) -> ListModel[FormSectionPublic]:
    if popup_id:
        from app.api.form_field.router import _resolve_schema_flow_id
        from app.api.popup.crud import popups_crud

        popup = popups_crud.get(db, popup_id)
        if not popup:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Popup not found",
            )
        # One flow's sections, never a merge across the popup's flows
        # (sdd/sales-flows-rediseno slice 3).
        flow_id = _resolve_schema_flow_id(db, popup_id, sales_flow_id)
        # Fetch all of them (small set) so the flag filter runs before
        # pagination — otherwise totals and pages are wrong.
        all_sections, _ = crud.form_sections_crud.find_by_flow(db, flow_id, limit=None)
        # Gate special-kind sections by current popup flags so the backoffice
        # renders consistently with the portal after a flag is toggled off.
        filtered = [s for s in all_sections if _section_allowed_by_flags(db, s)]
        total = len(filtered)
        sections = filtered[skip : skip + limit]
    else:
        sections, total = crud.form_sections_crud.find(db, skip=skip, limit=limit)

    return ListModel[FormSectionPublic](
        results=[FormSectionPublic.model_validate(s) for s in sections],
        paging=Paging(offset=skip, limit=limit, total=total),
    )


def _section_allowed_by_flags(db: Session, section: FormSections) -> bool:
    """Whether a special-kind section is asked, per its own flow.

    A section belongs to one flow, so the flag that hides it belongs to that
    flow too.
    """
    from app.api.sales_flow.resolver import config_for  # noqa: PLC0415

    if section.kind == FormSectionKind.SCHOLARSHIP.value:
        return bool(
            config_for(
                db,
                sales_flow_id=section.sales_flow_id,
                popup_id=section.popup_id,
            ).allows_scholarship
        )
    return True


@router.get("/{section_id}", response_model=FormSectionPublic)
async def get_form_section(
    section_id: uuid.UUID,
    db: AdminOrApiKeySession_FormsRead,
    _: AdminOrApiKey_FormsRead,
) -> FormSectionPublic:
    section = crud.form_sections_crud.get(db, section_id)

    if not section:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Form section not found",
        )

    return FormSectionPublic.model_validate(section)


@router.post("", response_model=FormSectionPublic, status_code=status.HTTP_201_CREATED)
async def create_form_section(
    section_in: FormSectionCreate,
    db: AdminOrApiKeySession_FormsWrite,
    current_user: AdminOrApiKey_FormsWrite,
) -> FormSectionPublic:
    from app.api.popup.crud import popups_crud
    from app.api.sales_flow.resolver import config_for  # noqa: PLC0415

    popup = popups_crud.get(db, section_in.popup_id)
    if not popup:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Popup not found",
        )

    if current_user.role == UserRole.SUPERADMIN:
        tenant_id = popup.tenant_id
    else:
        tenant_id = current_user.tenant_id

    # Rejects a flow belonging to another popup.
    from app.api.form_field.router import _resolve_schema_flow_id

    _resolve_schema_flow_id(db, section_in.popup_id, section_in.sales_flow_id)

    # Gate special-kind sections by popup feature flags and uniqueness.
    if section_in.kind != FormSectionKind.STANDARD:
        if (
            section_in.kind == FormSectionKind.SCHOLARSHIP
            and not config_for(
                db,
                sales_flow_id=section_in.sales_flow_id,
                popup_id=section_in.popup_id,
            ).allows_scholarship
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Popup does not allow scholarship",
            )

        # Uniqueness is per flow: two flows may each have their own
        # scholarship section (slice 3).
        existing = db.exec(
            select(FormSections).where(
                FormSections.sales_flow_id == section_in.sales_flow_id,
                FormSections.kind == section_in.kind.value,
            )
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"A section of kind '{section_in.kind.value}' already "
                    "exists for this sales flow"
                ),
            )

    section_data = section_in.model_dump()
    section_data["tenant_id"] = tenant_id
    section = FormSections(**section_data)

    db.add(section)
    db.commit()
    db.refresh(section)

    return FormSectionPublic.model_validate(section)


@router.patch("/{section_id}", response_model=FormSectionPublic)
async def update_form_section(
    section_id: uuid.UUID,
    section_in: FormSectionUpdate,
    db: AdminOrApiKeySession_FormsWrite,
    current_user: AdminOrApiKey_FormsWrite,
    token_payload: CallerToken,
) -> FormSectionPublic:
    section = crud.form_sections_crud.get(db, section_id)

    if not section:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Form section not found",
        )

    if (
        "protected" in section_in.model_fields_set
        and section_in.protected != section.protected
    ):
        logger.warning(
            "form_section.protection_changed section_id={} popup_id={} "
            "sales_flow_id={} label={!r} previous_protected={} "
            "protected={} actor_user_id={} actor_email={} actor_role={} "
            "via_api_key={} api_key_id={} request_id={}",
            section.id,
            section.popup_id,
            section.sales_flow_id,
            section.label,
            section.protected,
            section_in.protected,
            current_user.id,
            current_user.email,
            current_user.role,
            token_payload.via_api_key,
            token_payload.api_key_id,
            get_request_id(),
        )

    updated = crud.form_sections_crud.update(db, section, section_in)
    return FormSectionPublic.model_validate(updated)


@router.delete("/{section_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_form_section(
    section_id: uuid.UUID,
    db: AdminOrApiKeySession_FormsWrite,
    current_user: AdminOrApiKey_FormsWrite,
    token_payload: CallerToken,
) -> None:
    section = crud.form_sections_crud.get(db, section_id)

    if not section:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Form section not found",
        )

    if section.protected:
        logger.warning(
            "form_section.delete_rejected section_id={} popup_id={} "
            "sales_flow_id={} label={!r} protected={} actor_user_id={} "
            "actor_email={} actor_role={} via_api_key={} api_key_id={} "
            "request_id={}",
            section.id,
            section.popup_id,
            section.sales_flow_id,
            section.label,
            section.protected,
            current_user.id,
            current_user.email,
            current_user.role,
            token_payload.via_api_key,
            token_payload.api_key_id,
            get_request_id(),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete a protected section",
        )

    custom_field_count = db.exec(
        select(func.count())
        .select_from(FormFields)
        .where(FormFields.section_id == section.id)
    ).one()
    base_field_count = db.exec(
        select(func.count())
        .select_from(BaseFieldConfigs)
        .where(BaseFieldConfigs.section_id == section.id)
    ).one()
    logger.warning(
        "form_section.delete section_id={} popup_id={} sales_flow_id={} "
        "label={!r} kind={} protected={} custom_fields_unsectioned={} "
        "base_fields_unsectioned={} actor_user_id={} actor_email={} "
        "actor_role={} via_api_key={} api_key_id={} request_id={}",
        section.id,
        section.popup_id,
        section.sales_flow_id,
        section.label,
        section.kind,
        section.protected,
        custom_field_count,
        base_field_count,
        current_user.id,
        current_user.email,
        current_user.role,
        token_payload.via_api_key,
        token_payload.api_key_id,
        get_request_id(),
    )

    delete_translations_for_entity(db, "form_section", section.id)
    crud.form_sections_crud.delete(db, section)
