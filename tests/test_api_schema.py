from __future__ import annotations

import unittest

from app.main import app


class ApiSchemaTests(unittest.TestCase):
    def test_only_document_translation_endpoint_is_public(self) -> None:
        schema = app.openapi()
        paths = schema.get("paths", {})

        self.assertIn("/translate/document", paths)
        self.assertNotIn("/translate/pdf", paths)
        self.assertNotIn("/translate/pdf/advanced", paths)


if __name__ == "__main__":
    unittest.main()
