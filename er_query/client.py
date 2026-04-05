"""Firestore client functions for querying Expert Request (ER) data.

These functions are designed with simple, typed parameters that can be
easily exposed as MCP server tools. Each function connects to Firestore,
runs a filtered query, and returns only the subset of fields needed
(er_name, account_name, account_sub_region, assigned_ce_email, details).

Why Firestore instead of BigQuery?
    The adk_agent/.env config specifies DATABASE_ID and COLLECTION which are
    Firestore concepts. The sample data structure (nested objects, arrays)
    also fits Firestore's document model better than BigQuery's tabular
    format. Firestore provides millisecond reads ideal for MCP tool
    latency requirements.
"""

import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from google.cloud import firestore

# Fields to project from Firestore documents
_RETURN_FIELDS = [
    "er_name",
    "account_name",
    "account_sub_region",
    "assigned_ce_email",
    "details",
]

# Fields to always exclude from full document returns (large/internal)
_EXCLUDE_FIELDS = frozenset(
    {
        "embedding",
        "content_hash",
        "account_vector_id",
        "opportunity_vector_id",
        "vector_id",
        "last_embedded_at",
        "needs_embedding",
    }
)


def _get_firestore_client() -> firestore.Client:
    """Create and return a Firestore client using environment configuration.

    Loads connection settings from adk_agent/.env file including
    GOOGLE_CLOUD_PROJECT and DATABASE_ID.

    Returns:
        A configured Firestore client instance.
    """
    load_dotenv("adk_agent/.env")
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    database_id = os.getenv("DATABASE_ID")

    return firestore.Client(project=project_id, database=database_id)


def _get_collection_ref(
    client: firestore.Client | None = None,
) -> firestore.CollectionReference:
    """Get the Firestore collection reference for expert requests.

    Args:
        client: Optional Firestore client. If None, creates a new one.

    Returns:
        A CollectionReference pointing to the expert_requests collection.
    """
    load_dotenv("adk_agent/.env")
    collection_name = os.getenv("COLLECTION", "expert_requests_dev")

    if client is None:
        client = _get_firestore_client()

    return client.collection(collection_name)


def _doc_to_er_record(doc_dict: dict) -> dict:
    """Convert a Firestore document dict to an ERRecord-compatible dict.

    Extracts only the required fields from the full document and returns
    them as a plain dictionary.

    Args:
        doc_dict: The full Firestore document as a dictionary.

    Returns:
        A dictionary containing only the ER return fields:
        'er_name', 'account_name', 'account_sub_region',
        'assigned_ce_email', 'details'.

    Example return value:
        {
            'er_name': 'ER-431059',
            'account_name': 'Australian Postal Corporation',
            'account_sub_region': 'AUNZ',
            'assigned_ce_email': 'issein@google.com',
            'details': '[WHY]\\nExplore new use case...'
        }
    """
    return {field: doc_dict.get(field, "") for field in _RETURN_FIELDS}


def query_er_by_email(
    assigned_ce_email: str,
    client: firestore.Client | None = None,
) -> list[dict]:
    """Retrieve Expert Requests assigned to a specific CE by email.

    Queries the Firestore collection for all documents where the
    assigned_ce_email field matches the provided email address.

    Args:
        assigned_ce_email: The email address of the assigned Customer
            Engineer (e.g., 'weiyih@google.com').
        client: Optional Firestore client for dependency injection
            during testing. If None, creates a new client.

    Returns:
        A list of dictionaries, each containing:
        'er_name', 'account_name', 'account_sub_region',
        'assigned_ce_email', 'details'.

        Returns an empty list if no matching ERs are found.

    Example return value:
        [
            {
                'er_name': 'ER-431059',
                'account_name': 'Australian Postal Corporation',
                'account_sub_region': 'AUNZ',
                'assigned_ce_email': 'issein@google.com',
                'details': '[WHY]\\nExplore new use case...'
            }
        ]
    """
    collection_ref = _get_collection_ref(client)

    query = collection_ref.where(
        filter=firestore.FieldFilter("assigned_ce_email", "==", assigned_ce_email)
    )

    results = []
    for doc in query.stream():
        doc_dict = doc.to_dict()
        results.append(_doc_to_er_record(doc_dict))

    return results


def query_er_by_name(
    er_name: str,
    fields: str | None = None,
    client: firestore.Client | None = None,
) -> list[dict]:
    """Retrieve a specific Expert Request by its ER name, optionally returning only selected fields.

    Queries the Firestore collection for the document whose er_name matches
    the provided identifier. If `fields` is specified, only those fields are
    returned; otherwise all non-embedding fields are returned.

    This is useful for inspecting specific attributes of an ER, such as
    fsa_assets, fsa_status, workload_gross_revenue, etc.

    Args:
        er_name: The ER identifier (e.g., 'ER-431059'). Case-sensitive.
        fields: Optional comma-separated list of field names to return
            (e.g., 'fsa_status,product,details'). If None or empty,
            returns all fields except 'embedding' and 'content_hash'.
        client: Optional Firestore client for dependency injection
            during testing. If None, creates a new client.

    Returns:
        A list of dictionaries containing the requested fields.
        Typically returns 0 or 1 results since er_name should be unique.
        Each dict has an 'er_name' key plus the requested fields.

        Returns an empty list if no matching ER is found.

    Example return value:
        [
            {
                'er_name': 'ER-431059',
                'fsa_status': 'Completed',
                'product': 'Gemini Enterprise'
            }
        ]
    """
    collection_ref = _get_collection_ref(client)

    query = collection_ref.where(filter=firestore.FieldFilter("er_name", "==", er_name))

    results = []
    for doc in query.stream():
        doc_dict = doc.to_dict()

        if fields and fields.strip():
            # Parse comma-separated field names, strip whitespace
            requested_fields = [f.strip() for f in fields.split(",") if f.strip()]
            # Always include er_name for context
            record = {"er_name": doc_dict.get("er_name", "")}
            for field_name in requested_fields:
                if field_name != "er_name" and field_name in doc_dict:
                    record[field_name] = doc_dict[field_name]
                elif field_name != "er_name":
                    record[field_name] = None  # Field not found in document
        else:
            # Return all fields except excluded ones
            record = {k: v for k, v in doc_dict.items() if k not in _EXCLUDE_FIELDS}

        results.append(record)

    return results


def query_er_by_date(
    year: int,
    month: int | None = None,
    client: firestore.Client | None = None,
) -> list[dict]:
    """Retrieve Expert Requests filtered by creation date.

    Queries the Firestore collection for documents created within the
    specified year or year+month range, based on the 'created_at' field.

    The created_at field is stored as a native Firestore Timestamp
    (DatetimeWithNanoseconds). We construct datetime range boundaries
    and compare directly with datetime objects.

    Args:
        year: The year to filter by (e.g., 2025).
        month: Optional month to filter by (1-12). If None, returns
            all ERs for the entire year.
        client: Optional Firestore client for dependency injection
            during testing. If None, creates a new client.

    Returns:
        A list of dictionaries, each containing:
        'er_name', 'account_name', 'account_sub_region',
        'assigned_ce_email', 'details'.

        Returns an empty list if no matching ERs are found.

    Raises:
        ValueError: If year is negative or month is not in range 1-12.

    Example return value:
        [
            {
                'er_name': 'ER-431059',
                'account_name': 'Australian Postal Corporation',
                'account_sub_region': 'AUNZ',
                'assigned_ce_email': 'issein@google.com',
                'details': '[WHY]\\nExplore new use case...'
            }
        ]
    """
    if year < 0:
        raise ValueError(f"Year must be non-negative, got {year}")
    if month is not None and not (1 <= month <= 12):
        raise ValueError(f"Month must be between 1 and 12, got {month}")

    # Build date range boundaries
    if month is not None:
        start_dt = datetime(year, month, 1, tzinfo=timezone.utc)
        # Handle December -> next year January
        if month == 12:
            end_dt = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            end_dt = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    else:
        start_dt = datetime(year, 1, 1, tzinfo=timezone.utc)
        end_dt = datetime(year + 1, 1, 1, tzinfo=timezone.utc)

    collection_ref = _get_collection_ref(client)

    # Firestore stores created_at as a native Timestamp type
    # (DatetimeWithNanoseconds), so we compare with datetime objects directly
    query = collection_ref.where(
        filter=firestore.FieldFilter("created_at", ">=", start_dt)
    ).where(filter=firestore.FieldFilter("created_at", "<", end_dt))

    results = []
    for doc in query.stream():
        doc_dict = doc.to_dict()
        results.append(_doc_to_er_record(doc_dict))

    return results
