# Knowledge-Driven Voice Agent (Core AI Engine)

This repository contains the core Artificial Intelligence engine for a Knowledge-Driven Voice Agent. It acts as the intelligent middle layer between **Twilio** (telephony) and **OpenAI** (LLM and document parsing).

Currently, this project represents the **AI Module**. It handles ingesting knowledge, generating conversational personas, answering user queries via Conversational Retrieval-Augmented Generation (RAG with full transcript memory), and dynamically classifying conversational intents via LLMs.

---

## 🏗️ Architecture & How It Works

### 1. Document Ingestion (`/upload-doc/`)
When a business signs up, they upload a text/PDF document containing their knowledge (like an FAQ or a Menu).
* The AI reads this file via `app/extractor.py`.
* It generates a structured knowledge base (`reports/current_report.txt`).
* It generates a customized AI persona and greeting (`reports/current_script.txt`).

### 2. Call Initiation (`/voice`)
When a customer dials the Twilio phone number, Twilio hits this webhook.
* The system reads the custom greeting from `current_script.txt`.
* It returns an XML (TwiML) response instructing Twilio to speak the greeting and start listening (`<Gather>`) for user speech.

### 3. Voice Processing & Intent Detection (`/voice-process`)
When the customer finishes speaking, Twilio sends the transcribed text to this endpoint.
* **Conversational Memory:** `rag_answer.py` fetches the live transcript history so it always remembers what the user said previously.
* `rag_answer.py` analyzes the chat history + new text, and detects the **Intent** dynamically using OpenAI (`order_add`, `order_confirm`, `order_cancel`, `faq`, `escalation`).
* **If it's an FAQ:** The AI searches the uploaded knowledge base (`current_report.txt`) and answers contextually based on the full conversation history.
* **If it's an Order:** The AI pulls out JSON information (Items and Quantities) and asks the user to confirm.
* **If it's an Escalation:** The AI triggers a Twilio `<Dial>` tag to reroute the call.
* The generated response is spoken out loud over the phone using Twilio Text-to-Speech (`<Say>`).

### 4. Post-Call Summary (`/call-end`)
When the caller hangs up, Twilio hits this Status Callback URL.
* The system takes the full saved transcript of the conversation.
* It uses the AI to generate a brief summary (`call_summary.py`) and saves the log for historical tracking.

---

## 📡 API Endpoints (FastAPI)

* `POST /upload-doc/`: Generate a report and persona script from an uploaded business document.
* `POST /ask/`: A text-based debugging endpoint to test the RAG engine without calling the phone number.
* `POST /voice`: Twilio Voice Webhook (triggered when the call connects).
* `POST /voice-process`: Twilio Voice Processing (triggered after the user speaks).
* `POST /call-end`: Twilio Call Status Callback (triggered when the call ends).
* `GET /live-transcript/{call_id}`: Returns the live text transcript for an active call.

---

## ⚠️ BE Handoff: What the Backend Developer Needs to Do Next

**The Core AI logic is complete.** However, this project is currently built as a "Single-Tenant" prototype (handling one business at a time). To deploy this as a full SaaS application, the Backend Developer must implement the following architecture upgrades:

### 1. Implement Multi-Tenancy (Business Routing)
* **Current State:** The system hard-reads from a single file called `reports/current_report.txt` for every call.
* **Task:** When Twilio hits the `/voice` webhook, use the `To` phone number inside the payload request to look up the associated Business in your database. Dynamically load that specific business's knowledge file instead of the global `current_report.txt`.

### 2. Database Integration
* **Current State:** Transcripts, AI scripts, uploaded files, and logs are saved to local system `.txt` files and folders (`/reports`, `/uploads`). State is held in-memory.
* **Task:** Connect a database (PostgreSQL/MongoDB). Save the uploaded document text directly to the DB or to secure Cloud Storage (AWS S3). Store call states, transcripts, and call summaries in a relational format.

### 3. Activating the Order Pipeline
* **Current State:** In `voice_webhook.py`, when a user confirms an order, the AI prints the formulated final order JSON to the terminal using `print("FINAL ORDER JSON:", result["order"])`.
* **Task:** Take that JSON object and fire an API request to the specific business's real backend system, or save it into an `Orders` database table so the business owner can view the incoming order on their SaaS dashboard.

### 4. Dynamic Call Escalation
* **Current State:** If the user asks for a human, `voice_webhook.py` forwards the call to a hardcoded placeholder number `+1234567890`.
* **Task:** Fetch the actual Business Owner's representative phone number dynamically from the database and pass it into the `<Dial>` tag.

### 5. Vector Database for Large Documents (Optional but Recommended)
* **Current State:** `app/retriever.py` searches through the raw text file directly.
* **Task:** If businesses upload massive 100-page PDF documents, searching raw text is inefficient. Implement a Vector Database (like Pinecone, Qdrant, or pgvector) to store the knowledge as embeddings for hyper-fast semantic searching.

### 6. Streaming Audio (Future Latency Optimization)
* **Current State:** Relies on standard Twilio `<Gather>` webhooks. The bot must wait for the user to completely stop talking, then wait for ChatGPT to finish generating its entire response, before playback begins.
* **Task:** Introduce **Twilio Media Streams (WebSockets)** to stream the audio directly to the AI and stream text-to-speech back incrementally. This reduces latency from ~3-5 seconds down to ~800ms.

---

## 🚀 Setup & Installation (Local Development)

1. Clone the repository.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and fill in your keys:
   ```env
   OPENAI_API_KEY=your_key_here
   LLM_MODEL=gpt-4o-mini
   ```
4. Start the FastAPI server:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```
5. Use `ngrok` to expose your port to Twilio:
   ```bash
   ngrok http 8000
   ```
6. Put the generated ngrok URL into your Twilio Console Webhooks (`/voice` for Webhook, `/call-end` for Status Callback).
