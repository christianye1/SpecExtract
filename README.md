# SpecExtract

Welcome! This repository is a full-stack project for approaching a real-world engineering problem: **design and build a web application** that helps users work with construction specification PDFs and **Google Gemini**.

---

## Mission

Your task is to **design and build a simple web application** that allows users to upload PDF documents from construction specifications and extract project-related information using **Google Gemini**.

The focus is on async workflows, scale, and maintainable architecture — in the context of a realistic product feature.

---

## What to Build

Imagine you're part of a team that works on digitalizing construction specification documents.

Your goal is to:

- Let users upload one or more **PDFs** containing construction specs
- Extract structured information using Gemini, such as:
  - `Project ID`
  - `Project Name`
- Display the extracted information in a suitable user interface
- Let users **edit the extracted info** and **add comments**
- Ensure the UI remains **responsive and usable during the processing of specification files**
- Allow **multiple documents** to be uploaded and processed at the same time

You can think of this as a **mini production system**. What would you build if you were owning this feature?

- Process large documents (100s–1000s of pages) efficiently

---

## Tech stack (provided)

To help you get started, this repo includes:

- **Frontend**: React (Vite) + TypeScript  
- **Backend**: FastAPI + Python  
- **Gemini API access**: API key and example PDF upload patterns are wired in `server/main.py`

You're free to use additional libraries or (AI) tools where you see fit. The goal is to show **how you tackle the problem**.

### Frontend

You can start the React frontend with:

```bash
cd app
npm i
npm run dev
```

### Server

You can start the server with the commands below. It is best to install dependencies inside a virtual environment (recommended).

```bash
cd server
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create `server/.env` (see `server/.env.example`) and set `GEMINI_API_KEY`. Optionally:

```bash
# export GEMINI_MODEL="gemini-1.5-pro"
```

```bash
uvicorn main:app --reload
```

**Quick run (if dependencies are already installed):** `cd server` then `uvicorn main:app --reload`.

The backend exposes a simple job-based PDF upload API:

- `POST /api/upload`: upload one or more PDFs and receive `job_ids` immediately  
- `GET /api/jobs/{job_id}`: poll for `status`, `progress`, and extracted `result`

See `server/main.py` for the current implementation.

The file `main.py` also contains patterns you can use as a reference for PDF upload and Gemini extraction (including prompts).

---

## How it should work

You decide the architecture and look of the app, but here are some key requirements:

- PDF uploads should **not block** the server or UI.
- The application needs to process large documents (100s–1000s of pages) efficiently. Large PDFs may take **minutes** — plan for that.

Put your own example PDFs in a `specification_documents` directory at the repo root if you like; that folder and any `specification_documents.zip` are **not** tracked in Git (local only).

Data should be persisted to local files or a lightweight DB. That is up to you.

Users should always have a clear view of:

- What is processing  
- What is completed  
- If any errors occurred  

Use Google Gemini to extract data from uploaded PDFs. You can prompt however you like.

---

## What we are looking for

### Must-haves

- Clean, maintainable code  
- Clear, responsive, type-safe frontend UI  
- Scalable and performant processing  

### Nice-to-haves

- Tests for key components  
- Observability (e.g. logs, error handling)  
- Data persistence (DB or file-based)  
- Basic retry / error handling  
- PDF preview or download options  

---

## How to assess the work

When reviewing this project (or walking through it in a discussion), useful angles include:

- Your approach and decisions  
- What you would do differently in production  

Criteria that matter:

- **Technical execution** — Is the code functional and well-structured?  
- **Architecture & design** — Does the solution scale well? Can you explain tradeoffs?  
- **Communication** — Can you clearly describe your design and decisions?  

This project is not about building *everything* — it is about how you **approach** real-world engineering problems.

---

We’re excited to see how you approach this — happy building!
