import os

def fix_tests():
    for root, _, files in os.walk('tests'):
        for f in files:
            if not f.endswith('.py'):
                continue
            path = os.path.join(root, f)
            with open(path, 'r', encoding='utf-8') as file:
                content = file.read()
            
            orig = content
            
            # Replace route calls
            replacements = {
                'await upload(make_test_request("POST", "/upload"), mock_file)': 'await upload(make_test_request("POST", "/upload"), mock_file, auth=AuthContext())',
                'get_document_status(\n            make_test_request("GET", "/documents/doc-q/status"), "doc-q"\n        )': 'get_document_status(\n            make_test_request("GET", "/documents/doc-q/status"), "doc-q", auth=AuthContext()\n        )',
                'get_document_status(\n            make_test_request("GET", "/documents/doc-emb/status"), "doc-emb"\n        )': 'get_document_status(\n            make_test_request("GET", "/documents/doc-emb/status"), "doc-emb", auth=AuthContext()\n        )',
                'get_document_status(\n            make_test_request("GET", "/documents/doc-1/status"), "doc-1"\n        )': 'get_document_status(\n            make_test_request("GET", "/documents/doc-1/status"), "doc-1", auth=AuthContext()\n        )',
                'get_document_status(\n                make_test_request("GET", "/documents/missing-doc/status"),\n                "missing-doc",\n            )': 'get_document_status(\n                make_test_request("GET", "/documents/missing-doc/status"),\n                "missing-doc",\n                auth=AuthContext(),\n            )',
                'delete_document(\n                    make_test_request("DELETE", "/documents/doc-1"), "doc-1"\n                )': 'delete_document(\n                    make_test_request("DELETE", "/documents/doc-1"), "doc-1", auth=AuthContext()\n                )',
                'delete_document(\n                make_test_request("DELETE", "/documents/missing-doc"), "missing-doc"\n            )': 'delete_document(\n                make_test_request("DELETE", "/documents/missing-doc"), "missing-doc", auth=AuthContext()\n            )',
                'delete_document(\n                make_test_request("DELETE", "/documents/doc-1"), "doc-1"\n            )': 'delete_document(\n                make_test_request("DELETE", "/documents/doc-1"), "doc-1", auth=AuthContext()\n            )',
                'delete_document(\n                        make_test_request("DELETE", "/documents/doc-1"), "doc-1"\n                    )': 'delete_document(\n                        make_test_request("DELETE", "/documents/doc-1"), "doc-1", auth=AuthContext()\n                    )'
            }
            
            for old, new in replacements.items():
                content = content.replace(old, new)
                
            if 'test_upload_atomic.py' in f:
                content = content.replace('fake_create_document(self, file_name: str)', 'fake_create_document(self, file_name: str, **kwargs)')
                content = content.replace('fake_store_chunks(self, doc_id: str, chunk_records: list[ChunkRecord])', 'fake_store_chunks(self, doc_id: str, chunk_records: list[ChunkRecord], **kwargs)')
                content = content.replace('fake_cleanup(self, doc_id: str)', 'fake_cleanup(self, doc_id: str, **kwargs)')

            if 'test_ingestion_pipeline.py' in f:
                content = content.replace('mock_cleanup.assert_awaited_once_with("doc-store-fail")', 'mock_cleanup.assert_awaited_once_with("doc-store-fail", tenant_id=None)')
                content = content.replace('mock_update.assert_awaited_with(', 'mock_update.assert_awaited_with(tenant_id=None, ')
                # wait, mock_update is called with: mock_update.assert_awaited_with(doc_id="doc-store-fail", status="failed", error=...)
                # better to just replace auth=ANY or tenant_id=None where necessary.
                
            if 'auth=AuthContext()' in content and 'AuthContext' not in orig:
                content = 'from core.auth import AuthContext\n' + content
                
            if content != orig:
                with open(path, 'w', encoding='utf-8') as file:
                    file.write(content)

if __name__ == '__main__':
    fix_tests()
