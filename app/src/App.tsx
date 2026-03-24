import { useState } from 'react'
import './App.css'

interface UploadResult {
  project_id: string | null
  project_name: string | null
  source_filename: string
}

type Status = 'idle' | 'uploading' | 'success' | 'error'

function App() {
  const [file, setFile] = useState<File | null>(null)
  const [status, setStatus] = useState<Status>('idle')
  const [result, setResult] = useState<UploadResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0]
    if (selected) {
      if (!selected.name.toLowerCase().endsWith('.pdf')) {
        setError('Please select a PDF file')
        setFile(null)
        return
      }
      setFile(selected)
      setError(null)
      setStatus('idle')
      setResult(null)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!file) return

    setStatus('uploading')
    setError(null)
    setResult(null)

    try {
      const formData = new FormData()
      formData.append('file', file)

      const res = await fetch('/api/upload', {
        method: 'POST',
        body: formData,
      })

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}))
        throw new Error(errData.detail || res.statusText || 'Upload failed')
      }

      const data = (await res.json()) as UploadResult
      setResult(data)
      setStatus('success')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
      setStatus('error')
    }
  }

  const handleReset = () => {
    setFile(null)
    setResult(null)
    setError(null)
    setStatus('idle')
  }

  return (
    <main className="upload-mvp">
      <h1>SpecExtract</h1>
      <p className="subtitle">Upload a construction specification PDF to extract project details.</p>

      <form onSubmit={handleSubmit} className="upload-form">
        <div className="file-input-wrapper">
          <input
            type="file"
            id="pdf-upload"
            accept=".pdf"
            onChange={handleFileChange}
            disabled={status === 'uploading'}
          />
          <label htmlFor="pdf-upload" className="file-label">
            {file ? file.name : 'Choose a PDF file'}
          </label>
        </div>

        <div className="actions">
          <button
            type="submit"
            className="btn btn-primary"
            disabled={!file || status === 'uploading'}
          >
            {status === 'uploading' ? 'Processing…' : 'Extract'}
          </button>
          {(status === 'success' || status === 'error') && (
            <button type="button" className="btn btn-secondary" onClick={handleReset}>
              Upload another
            </button>
          )}
        </div>
      </form>

      {error && (
        <div className="message error" role="alert">
          {error}
        </div>
      )}

      {status === 'success' && result && (
        <div className="result-card">
          <h2>Extracted project details</h2>
          <dl>
            <dt>Project ID</dt>
            <dd>{result.project_id ?? '—'}</dd>
            <dt>Project Name</dt>
            <dd>{result.project_name ?? '—'}</dd>
            <dt>Source file</dt>
            <dd>{result.source_filename}</dd>
          </dl>
        </div>
      )}
    </main>
  )
}

export default App
