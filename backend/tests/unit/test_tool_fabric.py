import asyncio

from app.models.schemas import ToolBatchExecutionRequest, ToolExecutionRequest
from app.services.tool_fabric import tool_fabric_service


def test_tool_catalog_contract_shape() -> None:
    catalog = tool_fabric_service.list_catalog()
    assert catalog
    first = catalog[0]
    assert first.name
    assert isinstance(first.input_schema, dict)
    assert first.risk_level in {'LOW', 'MEDIUM', 'HIGH'}
    assert first.retry_policy.max_attempts >= 1


def test_tool_execute_dry_run_returns_contract() -> None:
    result = asyncio.run(
        tool_fabric_service.execute(
            ToolExecutionRequest(name='wikipedia.search', payload={'query': 'jarvis'}, dry_run=True)
        )
    )
    assert result.success is True
    assert result.output.get('dry_run') is True
    contract = result.output.get('contract')
    assert isinstance(contract, dict)
    assert contract.get('name') == 'wikipedia.search'


def test_tool_execute_resolves_explicit_version() -> None:
    result = asyncio.run(
        tool_fabric_service.execute(
            ToolExecutionRequest(name='wikipedia.search@1.0.0', payload={'query': 'jarvis'}, dry_run=True)
        )
    )
    assert result.success is True
    assert result.resolved_version == '1.0.0'
    assert result.requested_name == 'wikipedia.search@1.0.0'


def test_tool_batch_execute_counts() -> None:
    batch = asyncio.run(
        tool_fabric_service.batch_execute(
            ToolBatchExecutionRequest(
                requests=[
                    ToolExecutionRequest(name='wikipedia.search', payload={'query': 'jarvis'}, dry_run=True),
                    ToolExecutionRequest(name='wikidata.lookup', payload={'query': 'jarvis'}, dry_run=True),
                ],
                stop_on_error=True,
            )
        )
    )
    assert batch.success is True
    assert batch.success_count == 2
    assert batch.failed_count == 0
