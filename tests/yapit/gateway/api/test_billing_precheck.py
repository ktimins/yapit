"""The AI extraction precheck: estimates only the pages it is given, and not at all on an empty balance."""

from unittest.mock import AsyncMock, patch

import pymupdf
import pytest

from yapit.gateway.api.v1 import documents
from yapit.gateway.document.pdf import PER_PAGE_TOLERANCE, PROMPT_OVERHEAD_PER_PAGE
from yapit.gateway.document.types import ProcessorConfig
from yapit.gateway.exceptions import UsageLimitExceededError

CONFIG = ProcessorConfig(
    slug="gemini",
    supported_mime_types=frozenset({"application/pdf"}),
    max_pages=100,
    max_file_size=10 * 1024 * 1024,
    is_paid=True,
    output_token_multiplier=1,
    extraction_cache_prefix="gemini:test",
)


def _three_text_pages() -> bytes:
    doc = pymupdf.open()
    for i in range(3):
        doc.new_page().insert_text((72, 72), f"Page {i} " * 20)
    return doc.tobytes()


async def _precheck(pages: list[int] | None) -> None:
    await documents._billing_precheck(
        config=CONFIG,
        content=_three_text_pages(),
        content_type="application/pdf",
        content_hash="hash",
        user_id="user-1",
        pages=pages,
        db=AsyncMock(),
        billing_enabled=True,
        redis=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_estimates_only_the_given_pages():
    with (
        patch.object(documents, "get_available_usage", AsyncMock(return_value=(10_000_000, 0))),
        patch.object(documents, "check_usage_limit", AsyncMock()) as check,
        patch.object(documents, "create_reservation", AsyncMock()) as reserve,
        patch.object(documents, "log_event", AsyncMock()),
    ):
        await _precheck(pages=[1])

    # One text page: the prompt overhead plus its own tokens; the tolerance is one page's worth
    amount_checked = check.call_args.args[2]
    reserved = reserve.call_args.args[3]
    assert PROMPT_OVERHEAD_PER_PAGE < reserved < 2 * PROMPT_OVERHEAD_PER_PAGE
    assert amount_checked == reserved - PER_PAGE_TOLERANCE


@pytest.mark.asyncio
async def test_empty_balance_is_refused_without_opening_the_document():
    with (
        patch.object(documents, "get_available_usage", AsyncMock(return_value=(0, 0))),
        patch.object(documents, "estimate_document_tokens", side_effect=AssertionError("estimated")),
        pytest.raises(UsageLimitExceededError),
    ):
        await _precheck(pages=None)
