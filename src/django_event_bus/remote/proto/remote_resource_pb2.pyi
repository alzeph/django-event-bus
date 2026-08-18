from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class ResourceRequest(_message.Message):
    __slots__ = ("resource", "pk")
    RESOURCE_FIELD_NUMBER: _ClassVar[int]
    PK_FIELD_NUMBER: _ClassVar[int]
    resource: str
    pk: str
    def __init__(self, resource: _Optional[str] = ..., pk: _Optional[str] = ...) -> None: ...

class ResourceResponse(_message.Message):
    __slots__ = ("found", "data_json")
    FOUND_FIELD_NUMBER: _ClassVar[int]
    DATA_JSON_FIELD_NUMBER: _ClassVar[int]
    found: bool
    data_json: str
    def __init__(self, found: _Optional[bool] = ..., data_json: _Optional[str] = ...) -> None: ...
