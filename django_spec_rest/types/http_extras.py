from __future__ import annotations

from typing import Any, Generic

from rest_framework.request import Request
from typing_extensions import TypedDict, TypeVar

UserT = TypeVar("UserT", default=Any)


class HttpExtras(TypedDict, Generic[UserT], total=False):
    request: Request
    user: UserT
