import os
import glob
import logging
from pathlib import Path
from vector_memory import VectorMemory

log = logging.getLogger("lis.indexer")
logging.basicConfig(level=logging.INFO)

def chunk_text(text: str, chunk_size: int = 500) -> list[str]:
    """Split text into roughly equal chunks of words."""
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size):
        chunk = " ".join(words[i:i+chunk_size])
        chunks.append(chunk)
    return chunks

def extract_pdf_text(filepath: str) -> str:
    """Extract text from a PDF file using PyPDF2 if available."""
    try:
        import PyPDF2
        text = ""
        with open(filepath, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        return text
    except ImportError:
        log.warning("PyPDF2 not installed. Skipping PDF extraction. Run: pip install PyPDF2")
        return ""
    except Exception as e:
        log.error(f"Error reading PDF {filepath}: {e}")
        return ""

async def index_directory(directory_path: str):
    """Scan directory and index supported files into vector memory."""
    vmem = VectorMemory()
    log.info(f"Starting index of {directory_path}...")
    
    supported_extensions = ['.txt', '.md', '.py', '.json', '.csv', '.pdf']
    indexed_count = 0
    
    for root, dirs, files in os.walk(directory_path):
        # Skip common ignore dirs
        if any(ignore in root for ignore in ['.git', '__pycache__', 'node_modules', 'venv', '.gemini']):
            continue
            
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext not in supported_extensions:
                continue
                
            filepath = os.path.join(root, file)
            text = ""
            
            try:
                if ext == '.pdf':
                    text = extract_pdf_text(filepath)
                else:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        text = f.read()
                        
                if not text.strip():
                    continue
                    
                # Split into manageable chunks
                chunks = chunk_text(text)
                for i, chunk in enumerate(chunks):
                    # Store in vector memory
                    vmem.store(
                        text=chunk,
                        metadata={
                            "type": "document",
                            "source": filepath,
                            "filename": file,
                            "chunk": i
                        }
                    )
                indexed_count += 1
                log.info(f"Indexed {file} ({len(chunks)} chunks)")
                
            except UnicodeDecodeError:
                pass # Skip binary files that masquerade as text
            except Exception as e:
                log.error(f"Failed to index {file}: {e}")
                
    log.info(f"Indexing complete. Successfully indexed {indexed_count} files.")

if __name__ == "__main__":
    import asyncio
    # For testing: index the current jarvis directory
    asyncio.run(index_directory(os.path.dirname(os.path.abspath(__file__))))
