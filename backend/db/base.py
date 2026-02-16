from abc import ABC, abstractmethod
from typing import List, Tuple

# abstract base class that defines WHAT database operations we need
# all dbservices (sqlalchemy, supabas, mongodb etc.) must implement these methods.
# This ensures they're interchangeable.

class DatabaseService(ABC):

    @abstractmethod
    async def create_document(self, filename: str) -> str:
        # Create a document record and returns the document ID.
        pass
    
    @abstractmethod
    async def insert_chunks_batch(
        self, 
        doc_id: str, 
        chunks_with_embeddings: List[Tuple[str, List[float]]]
    ) -> List[str]:
        #insert multiple chunks and their embeddings return list of ids
        pass
    
    @abstractmethod
    async def get_document(self, doc_id: str) -> dict:
        #Retrieve a document by ID.
        pass
    
