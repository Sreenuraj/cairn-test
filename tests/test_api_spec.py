"""
Tests for OpenAPI ingestion, $ref resolution, and normalized operation hashing (T2.1, FR-A1).
"""

from cairn_test.plugins.api.spec import OpenAPISpec

SAMPLE_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Store API", "version": "1.0.0"},
    "paths": {
        "/orders": {
            "post": {
                "operationId": "createOrder",
                "summary": "Create order",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/OrderInput"}
                        }
                    }
                },
                "responses": {
                    "201": {
                        "description": "Created",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Order"}
                            }
                        }
                    }
                }
            }
        },
        "/orders/{id}": {
            "parameters": [
                {
                    "name": "id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"}
                }
            ],
            "get": {
                "operationId": "getOrder",
                "responses": {
                    "200": {
                        "description": "Order details",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Order"}
                            }
                        }
                    }
                }
            }
        }
    },
    "components": {
        "schemas": {
            "OrderInput": {
                "type": "object",
                "required": ["ref", "items"],
                "properties": {
                    "ref": {"type": "string"},
                    "items": {"type": "array"}
                }
            },
            "Order": {
                "type": "object",
                "required": ["id", "total"],
                "properties": {
                    "id": {"type": "string"},
                    "total": {"type": "number"},
                    "items": {"type": "array"}
                }
            }
        }
    }
}

def test_openapi_ingestion_and_ref_resolution():
    spec = OpenAPISpec(SAMPLE_SPEC)
    assert len(spec.operations_by_id) == 2
    assert "createOrder" in spec.operations_by_id
    assert "getOrder" in spec.operations_by_id

    # Verify $ref resolution for createOrder requestBody
    op_create = spec.get_operation("createOrder")
    assert op_create.method == "POST"
    assert op_create.path == "/orders"
    req_schema = op_create.request_body["content"]["application/json"]["schema"]
    assert req_schema["type"] == "object"
    assert "ref" in req_schema["properties"]
    assert "$ref" not in req_schema

    # Verify $ref resolution for responses
    resp_schema = op_create.responses["201"]["content"]["application/json"]["schema"]
    assert resp_schema["type"] == "object"
    assert "total" in resp_schema["properties"]

    # Verify path parameter inheritance on getOrder
    op_get = spec.get_operation("getOrder")
    assert op_get.method == "GET"
    assert len(op_get.parameters) == 1
    assert op_get.parameters[0]["name"] == "id"
    assert op_get.parameters[0]["in"] == "path"

    # Determinism: parsing the same spec produces identical op_hash
    spec2 = OpenAPISpec(SAMPLE_SPEC)
    assert spec2.get_operation("createOrder").op_hash == op_create.op_hash

    # Modified schema produces a different op_hash
    modified_spec = dict(SAMPLE_SPEC)
    modified_spec["components"]["schemas"]["OrderInput"]["properties"]["notes"] = {"type": "string"}
    spec_mod = OpenAPISpec(modified_spec)
    assert spec_mod.get_operation("createOrder").op_hash != op_create.op_hash

    print("OpenAPI ingestion, $ref resolution, and op_hash tests PASSED!")

if __name__ == "__main__":
    test_openapi_ingestion_and_ref_resolution()
