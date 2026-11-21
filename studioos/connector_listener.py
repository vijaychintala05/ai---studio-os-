"""Serve the existing connector endpoint on a separate Docker listener."""

from starlette.routing import Route, Router

from .main import app as studioos_app

# Handle the exact path regardless of Host. The inner app runs its normal request
# security middleware. Its startup and scheduler run only on the main listener.
app = Router(routes=[Route('/mcp', endpoint=studioos_app)], redirect_slashes=False)
