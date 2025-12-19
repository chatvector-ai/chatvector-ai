# ChatVector-AI  
### Open-Source Backend-First RAG Engine for Document Intelligence

ChatVector-AI is an open-source Retrieval-Augmented Generation (RAG) engine for ingesting, indexing, and querying unstructured documents such as PDFs and text files.

Think of it as an engine developers can use to build document-aware applications — such as research assistants, contract analysis tools, or internal knowledge systems — without having to reinvent the RAG pipeline.

<p>
  <img src="https://img.shields.io/badge/Status-Backend%20MVP-brightgreen" alt="Status">
  <img src="https://img.shields.io/badge/PRs-Welcome-brightgreen" alt="PRs Welcome">
  <img src="https://img.shields.io/badge/Python-FastAPI-blue" alt="Python FastAPI">
  <img src="https://img.shields.io/badge/AI-RAG%20Engine-orange" alt="AI RAG">
</p>

---

## 🔗 Quick Links

* **🚀 View Open [Issues](https://github.com/chatvector-ai/chatvector-ai/issues) & [Project Board](https://github.com/orgs/chatvector-ai/projects/2)**
* [🎥 Demo Video](https://www.loom.com/share/b7be8b165031450aad650144a71c1a10)
* [🎥 Setup Video](https://www.loom.com/share/8635d7e0a5a64953a4bf028360b74e25) — get running in ~10 minutes
* **[📘 Contributing Guide](CONTRIBUTING.md)** — **[Video](https://www.loom.com/share/c41bdbff541f47d49efcb48920cba382)**
* **[💬 Discussions](https://github.com/chatvector-ai/chatvector-ai/discussions)** — say hello
* **[📘 Development Notes](DEVELOPMENT.md)** — maintainer notes & reminders

---

## 🔎 What is ChatVector-AI?

ChatVector-AI provides a **clean, extensible backend foundation for RAG-based document intelligence**. It handles the full lifecycle of document Q&A:

* Document ingestion (PDF, text)
* Text extraction and chunking
* Vector embedding and storage
* Semantic retrieval
* LLM-powered answer generation

The goal is to offer a **developer-focused RAG engine** that can be embedded into other applications, tools, or products — not a polished end-user SaaS.

---

## 👥 Who is this for?

ChatVector-AI is designed for:

* **Developers** building document intelligence tools or internal knowledge systems
* **Backend engineers** who want a solid RAG foundation without heavy abstractions
* **AI/ML practitioners** experimenting with chunking, retrieval, and prompt strategies
* **Open-source contributors** interested in retrieval systems, embeddings, and LLM orchestration

---

## 🚀 Current Status

### Backend MVP (Core Engine)

The core RAG backend is **complete and functional**.

**What works today:**

* ✅ PDF text extraction
* ✅ Basic chunking pipeline
* ✅ Vector embeddings
* ✅ Semantic search (pgvector)
* ✅ LLM-powered answers
* ✅ Supabase integration

**Backend improvements in progress:**

* 🚧 Advanced chunking strategies
* 🚧 Error handling & logging
* 🚧 API rate limiting
* 🚧 Performance optimization
* 🚧 Authentication & access control

Frontend Demo: A lightweight UI for testing the backend API. Not production-ready.

---

## 🧠 Architecture Overview

### Backend Layer (Core)

* **FastAPI** — modern Python API framework with automatic OpenAPI docs
* **Uvicorn** — high-performance ASGI server
* **Design goals:** clarity, extensibility, and debuggability

### AI & Retrieval Layer

* **LangChain** — RAG orchestration
* **Google AI Studio (Gemini)** — LLM + embeddings
* **Features:** chunking, semantic retrieval, prompt construction

### Data Layer

* **Supabase** — PostgreSQL backend
* **pgvector** — native vector similarity search
* **Storage:** document metadata and embeddings

### Reference Frontend (Non-Core)

* **Next.js + TypeScript**
* Exists solely to demonstrate backend usage
* Not production-ready
* Subject to breaking changes

---

## 🎯 Quick Start: Run in 5 Minutes

## 🖥️ Backend Setup

<h4>Prerequisites</h4>
<ul>
  <li>Python 3.8+</li>
  <li>Supabase Account (Free) <a href="https://supabase.com/">Link</a></li>
  <li>Google AI API Key (Free Tier) <a href="https://aistudio.google.com/">Link</a></li>
</ul>

<h4>Setup Instructions</h4>

```bash
# 1. Fork and clone the repository
# First, click "Fork" on GitHub, then:
git clone https://github.com/YOUR_USERNAME/chatvector-ai.git

# 2. Set up API Keys
## Google AI Studio (Gemini API)
# - https://aistudio.google.com/
# - Sign in with your Google account
# - Create a new project
# - Click "Get Api Key"

## Supabase
# - https://supabase.com/
# - Sign in with your Google account
# - Create a new project
# - Get db url - project settings > Data API > Project URL > Copy URL
# - Get API key - project settings > API Keys > Click "Create new api keys" > Publishable Key

# 3. Set up environment

# Navigate to the backend folder
cd backend
# Create a .env file and add the following lines:
SUPABASE_URL=your_supabase_project_url_here
SUPABASE_KEY=your_supabase_anon_public_key_here
GEN_AI_KEY=your_google_ai_studio_api_key_here
# Replace each placeholder with the actual values from Step #2

# 4. Create and activate virtual environment
python -m venv venv
# On Mac: source venv/bin/activate
# On Windows: venv\Scripts\activate

# 5. Install dependencies
pip install -r requirements.txt

# 6. Set up Supabase database
# Go to Supabase project
# Navigate to the SQL Editor and run the following commands:

-- Enable vector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create documents table
CREATE TABLE documents (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  file_name TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Create document_chunks table
CREATE TABLE document_chunks (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  document_id UUID REFERENCES documents(id),
  chunk_text TEXT,
  embedding vector(768),
  created_at TIMESTAMP DEFAULT NOW()
);

-- Create vector search function
CREATE OR REPLACE FUNCTION match_chunks(
  query_embedding vector(768),
  match_count int DEFAULT 5,
  filter_document_id uuid DEFAULT NULL
)
RETURNS TABLE (
  id uuid,
  chunk_text text,
  similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    document_chunks.id,
    document_chunks.chunk_text,
    1 - (document_chunks.embedding <=> query_embedding) as similarity
  FROM document_chunks
  WHERE (filter_document_id IS NULL OR document_chunks.document_id = filter_document_id)
  ORDER BY document_chunks.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;

# 7. Return to project root and launch the backend
cd..
uvicorn backend.main:app --reload --port 8000
```

<h3>Test the API</h3>
<p><em>There is no Frontend yet - test everything directly in your browser!</em></p>

<p>Once running on <code>http://localhost:8000</code>, FastAPI provides automatic interactive documentation:</p>

<ol>
  <li><strong>Visit the root</strong>: <a href="http://localhost:8000">http://localhost:8000</a> - See welcome message</li>
  <li><strong>Explore the API Docs</strong>: <a href="http://localhost:8000/docs">http://localhost:8000/docs</a> - <strong>Interactive Swagger UI</strong> where you can test all endpoints</li>
</ol>

<h4>Try the Endpoints in the Docs:</h4>

<ul>
  <li><strong>Upload a PDF</strong>: 
    <ul>
      <li>Go to the <code>/upload</code> endpoint in the docs</li>
      <li>Click "Try it out"</li>
      <li>Choose a PDF file and execute</li>
      <li>Save the returned <code>document_id</code> for chatting</li>
    </ul>
  </li>
  
  <li><strong>Chat with your document</strong>:
    <ul>
      <li>Go to the <code>/chat</code> endpoint in the docs</li>
      <li>Click "Try it out"</li>
      <li>Enter your <code>document_id</code> and a question</li>
      <li>Get AI-powered answers from your PDF!</li>
    </ul>
  </li>
</ul>

## 🖥️ Frontend Setup
Note: The frontend serves as the web presence for the OSS, and as a testing demo -- but is not central to the actual OSS.

<h4>Prerequisites</h4>
<ul>
  <li>Node.js 18+</li>
  <li>npm or yarn</li>
</ul>

<h4>Setup Instructions</h4>

```bash
# 1. Navigate to frontend directory
cd frontend-demo

# 2. Install dependencies
npm install

# 3. Start development server
npm run dev

#4. Run in browser
The frontend will run on http://localhost:3000
```

---

## 🤝 Contributing

High-impact contribution areas:

* Ingestion & indexing pipelines
* Retrieval quality & evaluation
* Chunking strategies
* API design & refactoring
* Performance & scaling
* Documentation & examples

Frontend contributions are welcome but considered **non-core**.

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

---

## 📄 License

MIT License

⭐ Star the repo to follow progress and support the project.


