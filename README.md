# ChatVector-AI: Open Source Document Intelligence

> **Have conversations with your documents.** ChatVector-AI is a RAG (Retrieval-Augmented Generation) platform that lets you upload PDFs and ask questions in natural language.

<p align="center">
  <img src="https://img.shields.io/badge/Status-MVP%20Ready-brightgreen" alt="Status">
  <img src="https://img.shields.io/badge/PRs-Welcome-brightgreen" alt="PRs Welcome">
  <img src="https://img.shields.io/badge/Python-FastAPI-blue" alt="Python FastAPI">
  <img src="https://img.shields.io/badge/AI-RAG%20Pipeline-orange" alt="AI RAG">
</p>


## 🔗 Quick Links
- **🚀 View Open [Issues](https://github.com/chatvector-ai/chatvector-ai/issues) & [Project Board](https://github.com/orgs/chatvector-ai/projects/2)**  
- **[📘 Contributing Guide](CONTRIBUTING.md)** - How to submit your first PR.
- **[🎥 Setup Video](YOUR_LOOM_LINK_HERE)** - Get the project running in 5 minutes.
- **[💬 Join Discussions](https://github.com/chatvector-ai/chatvector-ai/discussions)** - Say hello!
`
<h3>🚀 Current Status: Basic Backend/MVP!</h3>

**The core RAG engine is complete and working!** We have a functional FastAPI backend that handles PDF uploads, vectorization, and AI-powered Q&A.

<table>
  <tr>
    <td><strong>What's Working (MVP)</strong></td>
    <td><strong>Backend Improvements Needed</strong></td>
    <td><strong>Frontend & Features</strong></td>
  </tr>
  <tr>
    <td>
      ✅ PDF Text Extraction<br>
      ✅ Basic Text Chunking<br>
      ✅ Vector Embeddings<br>
      ✅ Semantic Search<br>
      ✅ AI-Powered Answers<br>
      ✅ Supabase Integration
    </td>
    <td>
      🚧 Advanced Chunking Strategies<br>
      🚧 Error Handling & Logging<br>
      🚧 API Rate Limiting<br>
      🚧 Backend Refactoring<br>
      🚧 Performance Optimization<br>
      🚧 Proper Authentication
    </td>
    <td>
      🚧 Beautiful Frontend<br>
      🚧 User Authentication UI<br>
      🚧 Multiple File Types<br>
      🚧 Chat Interface<br>
      🚧 Deployment Ready
    </td>
  </tr>
</table>

**Now, we need your help to build the rest!** This is a community-driven project from the ground up.

## 🛠 Technology Stack Architecture

<h3>Frontend Layer</h3>
<ul>
  <li><strong>Next.js</strong> - React framework with App Router, SSR, and optimal performance</li>
  <li><strong>Deployment:</strong> Vercel for seamless CI/CD and global edge network</li>
  <li><strong>Features:</strong> Responsive UI, real-time chat interface, drag-and-drop uploads</li>
</ul>

<h3>Backend Layer</h3>
<ul>
  <li><strong>FastAPI</strong> - Modern Python web framework with automatic OpenAPI docs</li>
  <li><strong>Uvicorn</strong> - ASGI web server for high-performance async handling</li>
  <li><strong>Deployment:</strong> Docker containers on Railway for easy scaling</li>
  <li><strong>Features:</strong> Async request handling, WebSocket support, comprehensive API</li>
</ul>

<h3>AI & Processing Layer</h3>
<ul>
  <li><strong>LangChain</strong> - Orchestrates the entire RAG pipeline</li>
  <li><strong>Google AI Studio</strong> - Primary AI provider (Gemini models)</li>
  <li><strong>Embeddings:</strong> Google's embedding models for vector generation</li>
  <li><strong>Features:</strong> Text chunking, semantic search, prompt optimization</li>
</ul>

<h3>Data Layer</h3>
<ul>
  <li><strong>Supabase</strong> - All-in-one backend platform</li>
  <li><strong>PostgreSQL with pgvector</strong> - Native vector similarity search</li>
  <li><strong>Authentication:</strong> Built-in auth with session management</li>
  <li><strong>Storage:</strong> Document file storage and metadata</li>
</ul>

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

# 7. Launch the backend
uvicorn main:app --reload --port 8000
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

<h4>Prerequisites</h4>
<ul>
  <li>Node.js 18+</li>
  <li>npm or yarn</li>
</ul>

<h4>Setup Instructions</h4>

```bash
# 1. Navigate to frontend directory
cd frontend

# 2. Install dependencies
npm install

# 3. Start development server
npm run dev

#4. Run in browser
The frontend will run on http://localhost:3000
```

<p>The frontend includes:</p> <ul> <li>✅ Next.js 16 with React 19</li> <li>✅ TypeScript for type safety</li> <li>✅ Tailwind CSS for styling</li> <li>✅ ESLint for code quality</li> </ul><p><strong>Note:</strong> The frontend is a minimal scaffold waiting for contributors to build features!</p>

</div>

<br> <h2><Strong>🤝 Contribute to ChatVector-AI</Strong></h2>

We are actively seeking contributors of all types and skill levels! This is your chance to get involved with a cutting-edge AI project and help build something amazing from the ground up.

<p align="center"> <strong>🚀 Looking For:</strong> </p><table align="center"> <tr> <td align="center"> <strong>Frontend Developers</strong><br> Build the Next.js interface, chat UI, and user experience </td> <td align="center"> <strong>Backend Engineers</strong><br> Scale the FastAPI system, optimize RAG, and add features </td> </tr> <tr> <td align="center"> <strong>UI/UX Designers</strong><br> Design beautiful interfaces and improve user workflows </td> <td align="center"> <strong>DevOps Engineers</strong><br> Set up Docker, deployment, and CI/CD pipelines </td> </tr> <tr> <td align="center"> <strong>AI/ML Enthusiasts</strong><br> Optimize prompts, chunking strategies, and model performance </td> <td align="center"> <strong>Technical Writers</strong><br> Improve documentation and create tutorials </td> </tr> </table>

<h5>All skill levels welcome!</h5>
<h5>Example tasks:</h5>
🎯  Beginners
<ul> <li>🚀 <strong>Build the initial Next.js frontend</strong> - Create the first React components</li> <li>📄 <strong>Add support for <code>.txt</code> files</strong> - Simple file type expansion</li> <li>📝 <strong>Create better documentation</strong> - Help others get started</li> <li>🐛 <strong>Improve error messages</strong> - Make the app more user-friendly</li> <li>🎨 <strong>Design UI mockups</strong> - Create the visual foundation</li> </ul>

💪 Intermediate/Advanced

<ul> <li>🏗️ <strong>Refactor backend architecture</strong> - Split the monolith into clean modules</li> <li>🔐 <strong>Implement Supabase authentication</strong> - Add user accounts and security</li> <li>🐳 <strong>Add Docker & deployment scripts</strong> - Make deployment seamless</li> <li>🧠 <strong>Advanced RAG optimizations</strong> - Improve AI response quality</li> <li>⚡ <strong>Performance optimization</strong> - Speed up vector search and processing</li> </ul>

📥 Get Started Now!

<ol> <li>📖 <strong>Check out our <a href="CONTRIBUTING.md">Contributing Guide</a></strong></li> <li>🎯 <strong>Look for issues labeled <a href="https://github.com/chatvector-ai/chatvector-ai/issues?q=is%3Aopen+is%3Aissue+label%3A%22good+first+issue%22">good first issue</a></strong></li> <li>👋 <strong>Introduce yourself in the <a href="https://github.com/chatvector-ai/chatvector-ai/discussions">project discussions</a></strong></li> <li>🚀 <strong>Submit your first PR and join the team!</strong></li> </ol><p align="center"> <strong>No contribution is too small! Whether you're fixing a typo or building a major feature, we welcome your help.</strong> </p>

<div align="center">

⭐ Star the repo to show your interest and stay updated!

📄 License
In Progress...

</div>
