"""AWS serverless backend: Lambda handlers and the DynamoDB repository.

This package imports only the standard library, ``shared`` and boto3/botocore
(enforced by the import-boundary test) so the Lambda bundle stays dependency
free. Handlers and the repository are added by later features; this module only
establishes the package boundary.
"""
