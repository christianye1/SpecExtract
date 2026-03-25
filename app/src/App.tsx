import { useState } from 'react'
import './App.css'

/** Matches server FIXED_METADATA_KEYS + additional_metadata + source_filename */
interface UploadResult {
  project_id: string | null
  project_name: string | null
  cost: string | null
  date: string | null
  client: string | null
  building_owner: string | null
  site_location: string | null
  additional_metadata: Record<string, string>
  source_filename: string
}

const FIXED_FIELD_LABELS: Record<string, string> = {
  project_id: 'Project ID',
  project_name: 'Project name',
  cost: 'Cost / contract value',
  date: 'Relevant date',
  client: 'Client',
  building_owner: 'Building owner',
  site_location: 'Site location',
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
        const errData = (await res.json().catch(() => ({}))) as { detail?: unknown }
        const detail = errData.detail
        const msg =
          typeof detail === 'string'
            ? detail
            : detail !== undefined
              ? JSON.stringify(detail, null, 2)
              : res.statusText || 'Upload failed'
        throw new Error(msg)
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

  const extraEntries =
    result?.additional_metadata && Object.keys(result.additional_metadata).length > 0
      ? Object.entries(result.additional_metadata)
      : []

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
          <h2>Extracted metadata</h2>
          <dl>
            {Object.keys(FIXED_FIELD_LABELS).map((key) => (
              <div key={key} className="result-row">
                <dt>{FIXED_FIELD_LABELS[key]}</dt>
                <dd>{(result[key as keyof UploadResult] as string | null) ?? '—'}</dd>
              </div>
            ))}
            <div className="result-row">
              <dt>Source file</dt>
              <dd>{result.source_filename}</dd>
            </div>
          </dl>

          {extraEntries.length > 0 && (
            <>
              <h3 className="result-subheading">Additional fields (model)</h3>
              <dl>
                {extraEntries.map(([k, v]) => (
                  <div key={k} className="result-row">
                    <dt>{k.replace(/_/g, ' ')}</dt>
                    <dd>{v}</dd>
                  </div>
                ))}
              </dl>
            </>
          )}
        </div>
      )}
    </main>
  )
}

export default App
