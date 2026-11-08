"""``REST_TRANSPORT`` - the name this package stamps on the context of a call it serves."""

from __future__ import annotations

from typing import Final

REST_TRANSPORT: Final = "rest"
"""What ``call_context["transport"]`` reads on a call a view of this package serves.

The key is the kernel's (``TRANSPORT_KEY``) and the value this package's, a plain
string, so ``call_context["transport"] == "rest"`` holds with nothing imported. A view
stamps it on the request's one dict (``view_call_context``). A serializer of this
package running under another transport's ``dispatch`` leaves that transport's stamp
alone, and a context handed in by hand reads as whatever its caller wrote."""
