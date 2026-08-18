#!/usr/bin/env bash
# Régénère les stubs gRPC à partir de remote_resource.proto.
#
# Regenerates the gRPC stubs from remote_resource.proto.
#
# protoc importe les modules générés par leur nom de fichier nu (import
# "remote_resource_pb2"), ce qui casse une fois le fichier déplacé dans
# le package django_event_bus.remote.proto: ce script corrige l'import
# du fichier *_pb2_grpc.py en import relatif après génération.
#
# protoc imports generated modules by their bare filename (import
# "remote_resource_pb2"), which breaks once the file lives inside the
# django_event_bus.remote.proto package: this script fixes the
# *_pb2_grpc.py file's import into a relative import after generation.

set -euo pipefail

PROTO_DIR="src/django_event_bus/remote/proto"

uv run python -m grpc_tools.protoc \
    -I "${PROTO_DIR}" \
    --python_out="${PROTO_DIR}" \
    --grpc_python_out="${PROTO_DIR}" \
    --pyi_out="${PROTO_DIR}" \
    "${PROTO_DIR}/remote_resource.proto"

sed -i \
    's/^import remote_resource_pb2 as remote__resource__pb2$/from . import remote_resource_pb2 as remote__resource__pb2/' \
    "${PROTO_DIR}/remote_resource_pb2_grpc.py"

echo "Stubs régénérés / stubs regenerated dans ${PROTO_DIR}"
