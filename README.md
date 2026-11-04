# Legal RAG Intelligence

An intelligent legal contract analysis application that uses a two-step Retrieval-Augmented Generation (RAG) pipeline:
1. **CUAD RoBERTa**: Extracts exact evidence clauses from the document based on the 41-category Contract Understanding Atticus Dataset (CUAD).
2. **Google Gemini LLM**: Synthesizes the extracted clause into a readable, human-friendly response explaining conditions, penalties, and exceptions.

## Quickstart Setup

### 1. Clone the repository
```bash
git clone https://github.com/binaryan005/rag_project.git
cd rag_project
```

### 2. Backend Setup
```bash
cd backend

# Create a virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure your API key
cp .env.example .env
```
Open the `.env` file and add your `GEMINI_API_KEY`. Get one for free at [Google AI Studio](https://aistudio.google.com/app/apikey).

*Note: The CUAD RoBERTa model (~500MB) will automatically download from Hugging Face the first time you run the server!*

### 3. Start the Backend Server
```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Start the Frontend
Open a new terminal window and run the React app:
```bash
cd frontend
npm install
npm run dev
```

### 5. Access the App
Open your browser and navigate to: **http://localhost:5500**

You can upload PDF or DOCX contracts, run full CUAD analysis, or ask natural language queries about the document.