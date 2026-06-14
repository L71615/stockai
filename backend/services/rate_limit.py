"""StockAI — shared rate limiters (slowapi)"""

from slowapi import Limiter
from slowapi.util import get_remote_address

# AI endpoints: 20 req/min (costly)
limiter_ai = Limiter(key_func=get_remote_address, default_limits=["20/minute"])

# Market data: 120 req/min (high frequency)
limiter_market = Limiter(key_func=get_remote_address, default_limits=["120/minute"])