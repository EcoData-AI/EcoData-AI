import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, type Document } from '@/lib/api'

/**
 * Milestone 5: upload PDF/TXT/Markdown/CSV/code, list what's been ingested,
 * delete. Retrieval itself is automatic per chat turn (see
 * docs/ARCHITECTURE.md, "Documents and retrieval") — there is no "search"
 * control here, only the corpus you're building.
 */
export function Knowledge() {
  const [documents, setDocuments] = useState<Document[]>([])
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const load = useCallback(async () => {
    setDocuments(await api.listDocuments())
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const upload = async (file: File) => {
    setUploading(true)
    setError(null)
    try {
      const document = await api.uploadDocument(file)
      setDocuments((prev) => [document, ...prev])
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not upload that file.')
    } finally {
      setUploading(false)
    }
  }

  const remove = async (document: Document) => {
    if (!window.confirm(`Delete "${document.title}"? This cannot be undone.`)) return
    await api.deleteDocument(document.id)
    setDocuments((prev) => prev.filter((d) => d.id !== document.id))
  }

  return (
    <div className="panel">
      <div className="panel__inner">
        <h2>Knowledge</h2>
        <p className="panel__lede">
          Documents GAIA can search. When a chat message matches something you've uploaded, the
          matching passages are retrieved and cited in the reply — no need to mention the
          document by name.
        </p>

        <div className="row" style={{ margin: '18px 0' }}>
          <button
            className="btn btn--primary"
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
          >
            {uploading ? 'Uploading…' : 'Upload a document…'}
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.txt,.md,.markdown,.csv,.py,.js,.ts,.tsx,.jsx,.json,.yaml,.yml,.toml,.html,.css,.sh,.rs,.go,.java,.c,.cpp,.h,.sql"
            hidden
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) void upload(file)
              event.target.value = ''
            }}
          />
        </div>

        {error && (
          <div className="notice notice--error" style={{ marginBottom: 16 }}>
            <div className="notice__body">{error}</div>
          </div>
        )}

        {documents.length === 0 ? (
          <p style={{ color: 'var(--text-muted)' }}>Nothing uploaded yet.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Type</th>
                <th>Chunks</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {documents.map((document) => (
                <tr key={document.id}>
                  <td>{document.title}</td>
                  <td>
                    <span className="tag tag--muted">{document.media_type}</span>
                  </td>
                  <td>{document.chunk_count}</td>
                  <td>
                    <button
                      className="btn btn--ghost"
                      aria-label="Delete document"
                      onClick={() => void remove(document)}
                    >
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
