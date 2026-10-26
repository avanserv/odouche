"""The request that lets the caller's address connect to a branch's builds with `ssh`, which changes state on Odoo.sh."""

import ipaddress

from odouche._upstream.reader import Reader
from odouche._upstream.transport import Transport, state_changing


_OPERATION = "allow_ip"


@state_changing
def allow_ip(transport: Transport, branch_id: int) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """Allow the address Odoo.sh sees this request come from, and return it. The request carries no address."""
    answer = Reader(_OPERATION, transport.change(_OPERATION, f"/app/branch/{branch_id}/allow_ip"))

    try:
        return ipaddress.ip_address(answer.text("result"))
    except ValueError:
        raise answer.changed("result") from None
