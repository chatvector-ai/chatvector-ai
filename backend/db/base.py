from abc import ABC, abstractmethod
from core.models import async_session, Document, DocumentChunk

# abstract base class that defines WHAT database operations we need
# all dbservices (sqlalchemy, supabas, mongodb etc.) must implement these methods.
# This ensures they're interchangeable.

class DatabaseService(ABC):

    # create a document record and returns the document id.
    @abstractmethod
    async def create_document(self, filename: str) -> str:
        pass
    
    #insert multiple chunks and their embeddings return list of ids
    @abstractmethod
    async def store_chunks_with_embeddings(
        self, 
        doc_id: str, 
        chunks_with_embeddings: list[tuple[str, list[float]]]
    ) -> list[str]:
        pass
    
    #grab a document by id
    @abstractmethod
    async def get_document(self, doc_id: str) -> dict:
        pass

    # Find chunks similar to the query embedding using vector similarity.
    # return List of DocumentChunk objects sorted by similarity
    @abstractmethod
    async def find_similar_chunks(
        self,
        doc_id: str,
        query_embedding: list[float],
        match_count: int = 5
    ) -> list[DocumentChunk]:
        pass
    
