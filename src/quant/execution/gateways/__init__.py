"""Gateway adapter boundary contracts; concrete broker SDKs stay below this package."""

from quant.execution.gateways.contracts import (
    DispatchCertainty,
    GatewayContractError,
    GatewayDispatchResult,
    GatewayTransport,
    validate_gateway_submit,
    verify_gateway_dispatch_result,
)

__all__ = [
    "DispatchCertainty",
    "GatewayContractError",
    "GatewayDispatchResult",
    "GatewayTransport",
    "validate_gateway_submit",
    "verify_gateway_dispatch_result",
]
