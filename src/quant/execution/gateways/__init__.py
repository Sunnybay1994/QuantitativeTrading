"""Gateway adapter boundary contracts; concrete broker SDKs stay below this package."""

from quant.execution.gateways.contracts import (
    DispatchCertainty,
    GatewayCancelResult,
    GatewayCancelTransport,
    GatewayContractError,
    GatewayDispatchResult,
    GatewayTransport,
    validate_gateway_cancel,
    validate_gateway_submit,
    verify_gateway_cancel_result,
    verify_gateway_dispatch_result,
)
from quant.execution.gateways.paper import (
    PaperCancelPlan,
    PaperClock,
    PaperFaultPlan,
    PaperFill,
    PaperFillPolicy,
    PaperGateway,
    PaperGatewayError,
    PaperSubmitPlan,
)

__all__ = [
    "DispatchCertainty",
    "GatewayCancelResult",
    "GatewayCancelTransport",
    "GatewayContractError",
    "GatewayDispatchResult",
    "GatewayTransport",
    "PaperCancelPlan",
    "PaperClock",
    "PaperFaultPlan",
    "PaperFill",
    "PaperFillPolicy",
    "PaperGateway",
    "PaperGatewayError",
    "PaperSubmitPlan",
    "validate_gateway_cancel",
    "validate_gateway_submit",
    "verify_gateway_cancel_result",
    "verify_gateway_dispatch_result",
]
