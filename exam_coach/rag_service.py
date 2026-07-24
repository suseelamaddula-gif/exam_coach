import re
import math
import uuid
import logging

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

logger = logging.getLogger(__name__)

def cosine_similarity(v1, v2):
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot_product = sum(x * y for x, y in zip(v1, v2))
    norm_v1 = math.sqrt(sum(x * x for x in v1))
    norm_v2 = math.sqrt(sum(x * x for x in v2))
    if norm_v1 == 0.0 or norm_v2 == 0.0:
        return 0.0
    return dot_product / (norm_v1 * norm_v2)

def keyword_overlap_score(query, text):
    """Fallback text similarity score based on term matching."""
    query_words = set(re.findall(r'\w+', query.lower()))
    text_words = set(re.findall(r'\w+', text.lower()))
    if not query_words:
        return 0.0
    overlap = len(query_words.intersection(text_words))
    return overlap / len(query_words)

class RAGService:
    def __init__(self, ai_service):
        self.ai_service = ai_service

    def extract_text(self, file_stream, filename):
        """Extracts text from a file stream based on extension."""
        text = ""
        try:
            if filename.lower().endswith(".pdf"):
                if PdfReader is None:
                    raise ImportError("pypdf is not installed. Unable to parse PDF.")
                reader = PdfReader(file_stream)
                for page_num, page in enumerate(reader.pages):
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
                logger.info("Successfully extracted %d characters from PDF: %s", len(text), filename)
            else:
                # Treat as plain text
                text = file_stream.read().decode("utf-8", errors="ignore")
                logger.info("Successfully read %d characters from text file: %s", len(text), filename)
        except Exception as e:
            logger.exception("Error extracting text from file %s", filename)
            raise e
        return text

    def chunk_text(self, text, chunk_size=800, overlap=150):
        """Splits text into overlapping chunks."""
        if not text:
            return []
        
        # Clean whitespaces
        text = re.sub(r'\s+', ' ', text).strip()
        
        chunks = []
        start = 0
        text_len = len(text)
        
        while start < text_len:
            end = min(start + chunk_size, text_len)
            
            # If not at end, try to find a natural boundary (period, question mark, newline, or space)
            if end < text_len:
                # Look back up to 100 characters for a sentence ender
                boundary = -1
                for i in range(end, max(end - 100, start), -1):
                    if text[i] in {'.', '?', '!'}:
                        boundary = i + 1
                        break
                
                # Fall back to space boundary if no sentence ender found
                if boundary == -1:
                    for i in range(end, max(end - 50, start), -1):
                        if text[i] == ' ':
                            boundary = i
                            break
                            
                if boundary != -1:
                    end = boundary
                    
            chunks.append(text[start:end].strip())
            start = end - overlap
            if start >= text_len or end == text_len:
                break
                
        return chunks

    def process_and_index_document(self, file_stream, filename):
        """Extracts, chunks, and creates vectors for document."""
        text = self.extract_text(file_stream, filename)
        chunks = self.chunk_text(text)
        
        if not chunks:
            return None
            
        doc_id = str(uuid.uuid4())
        logger.info("Chunked document '%s' into %d passages", filename, len(chunks))
        
        # Generate embeddings in batch if AI is configured
        embeddings = None
        if self.ai_service.is_configured():
            try:
                embeddings = self.ai_service.get_embeddings(chunks)
            except Exception as e:
                logger.warning("RAG embedding generation failed: %s. Using keyword fallback search.", e)
        
        indexed_chunks = []
        for idx, chunk in enumerate(chunks):
            embedding = embeddings[idx] if (embeddings and idx < len(embeddings)) else None
            indexed_chunks.append({
                "id": f"{doc_id}_{idx}",
                "text": chunk,
                "embedding": embedding
            })
            
        return {
            "id": doc_id,
            "filename": filename,
            "chunks": indexed_chunks,
            "character_count": len(text)
        }

    def search_similar_chunks(self, query, documents, top_k=3):
        """Searches across a list of indexed documents for top_k matches."""
        if not query or not documents:
            return []
            
        # Compile all chunks from all active documents
        all_chunks = []
        for doc in documents.values():
            all_chunks.extend(doc.get("chunks", []))
            
        if not all_chunks:
            return []
            
        # Try semantic search if AI is active and embeddings exist
        query_embedding = None
        if self.ai_service.is_configured() and any(c.get("embedding") is not None for c in all_chunks):
            query_embedding = self.ai_service.get_embeddings(query)
            
        scored_chunks = []
        for chunk in all_chunks:
            chunk_embedding = chunk.get("embedding")
            if query_embedding and chunk_embedding:
                score = cosine_similarity(query_embedding, chunk_embedding)
            else:
                score = keyword_overlap_score(query, chunk["text"])
            scored_chunks.append((chunk, score))
            
        # Sort by score descending
        scored_chunks.sort(key=lambda x: x[1], reverse=True)
        
        # Return top-k
        return [
            {
                "text": chunk["text"],
                "score": round(score, 4)
            }
            for chunk, score in scored_chunks[:top_k]
        ]
