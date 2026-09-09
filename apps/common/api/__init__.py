"""
Standardized API response helpers.

All API responses follow a consistent envelope format:
  Success: {"success": true, "data": {...}, "meta": {...}}
  Error:   {"success": false, "error": {"code": "...", "message": "...", "fields": {...}}}
"""

from rest_framework.response import Response
from rest_framework import status as http_status


def success_response(data=None, meta=None, status=http_status.HTTP_200_OK):
    """Return a standardized success response."""
    body = {"success": True, "data": data}
    if meta is not None:
        body["meta"] = meta
    return Response(body, status=status)


def created_response(data=None, meta=None):
    """Return a standardized 201 response."""
    return success_response(data=data, meta=meta, status=http_status.HTTP_201_CREATED)


def error_response(code, message, fields=None, status=http_status.HTTP_400_BAD_REQUEST):
    """Return a standardized error response."""
    error = {"code": code, "message": message}
    if fields:
        error["fields"] = fields
    return Response({"success": False, "error": error}, status=status)
