from app.tools.report_utils.tool import _run

from . import service


def register(mcp):
    @mcp.tool()
    async def inspect_asyncapi_document(content: str, limit: int = 20) -> str:
        """Inspect selected channels, send/receive operations, messages,
        content types and shallow payload shapes in supplied AsyncAPI 3.0.0
        JSON/YAML. Not full specification validation. External refs are never
        fetched; no broker or file access. Input at most 200000 chars, up to
        500 channels/operations and 500 messages per channel; limit 1-50.
        """
        return await _run(service.inspect_asyncapi_document, content, limit)

    @mcp.tool()
    async def compare_asyncapi_contracts(before: str, after: str, limit: int = 20) -> str:
        """Compare selected supplied AsyncAPI 3.0.0 channel, message and
        operation declarations by exact full IDs. Reports uncertain references
        and shallow schema changes, not a complete compatibility verdict.
        Offline; each input at most 200000 chars; limit 1-50.
        """
        return await _run(service.compare_asyncapi_contracts, before, after, limit)

    @mcp.tool()
    async def validate_asyncapi_json_message(spec: str, channel_id: str, message_id: str,
                                             payload: str, limit: int = 20) -> str:
        """Validate supplied JSON payload against one AsyncAPI 3.0.0 channel
        message. Supports a restricted AsyncAPI Schema Object or explicit JSON
        Schema Draft 7 and local component-schema refs. Rejects Avro/Protobuf,
        remote refs, custom dialects and discriminator semantics. Errors omit
        payload values. Offline three-second worker; inputs at most 200000
        chars; limit 1-50.
        """
        return await _run(service.validate_asyncapi_json_message, spec, channel_id, message_id, payload, limit)

    @mcp.tool()
    async def validate_cloudevents_json(content: str, limit: int = 20) -> str:
        """Check selected CloudEvents 1.0 structured JSON envelope rules for
        one supplied event: required/optional attribute types, basic URI/time
        syntax, extension value types, and data vs data_base64. Not full
        conformance or payload validation. Never returns attribute/payload
        values. Offline; input at most 200000 chars; limit 1-50.
        """
        return await _run(service.validate_cloudevents_json, content, limit)
