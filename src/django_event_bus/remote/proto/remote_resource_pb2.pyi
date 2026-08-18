from google.protobuf import struct_pb2 as _struct_pb2
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ResourceRequest(_message.Message):
    __slots__ = ("resource", "pk")
    RESOURCE_FIELD_NUMBER: _ClassVar[int]
    PK_FIELD_NUMBER: _ClassVar[int]
    resource: str
    pk: str
    def __init__(self, resource: _Optional[str] = ..., pk: _Optional[str] = ...) -> None: ...

class ResourceResponse(_message.Message):
    __slots__ = ("found", "data")
    FOUND_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    found: bool
    data: _struct_pb2.Struct
    def __init__(self, found: _Optional[bool] = ..., data: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...
