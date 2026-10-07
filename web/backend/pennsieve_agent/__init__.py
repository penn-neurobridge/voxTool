"""Messages for talking to the Pennsieve agent over gRPC.

`agent.proto` is copied unchanged from github.com/Pennsieve/pennsieve-agent at
tag 1.8.10 (Apache-2.0, api/v1/agent.proto), the agent version VoxTool was
tested against. `agent_pb2.py` is generated from it and must not be edited by
hand. VoxTool only uses it to ask the agent for a session token
(`ReAuthenticate`), so the service stubs are not generated at all.

To regenerate after updating the proto (protobuf 5.x runtime, see
requirements-desktop.txt):

    pip install "grpcio-tools>=1.71,<1.72"
    cd web/backend/pennsieve_agent
    python -m grpc_tools.protoc -I. --python_out=. agent.proto
"""
