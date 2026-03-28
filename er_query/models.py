"""Pydantic models for Expert Request data."""

from pydantic import BaseModel, Field


class ERRecord(BaseModel):
    """Represents a subset of Expert Request fields returned by queries.

    This model contains only the fields relevant for MCP tool responses,
    keeping the payload lightweight and focused.

    Attributes:
        er_name: The unique ER identifier (e.g., 'ER-431059').
        account_name: The customer account name.
        account_sub_region: The sub-region of the account (e.g., 'AUNZ').
        assigned_ce_email: The email of the assigned Customer Engineer.
        details: The detailed description of the engagement.
    """

    er_name: str = Field(description="The unique ER identifier (e.g., 'ER-431059')")
    account_name: str = Field(description="The customer account name")
    account_sub_region: str = Field(
        description="The sub-region of the account (e.g., 'AUNZ')"
    )
    assigned_ce_email: str = Field(
        description="The email of the assigned Customer Engineer"
    )
    details: str = Field(description="The detailed description of the engagement")

    model_config = {"frozen": True}
