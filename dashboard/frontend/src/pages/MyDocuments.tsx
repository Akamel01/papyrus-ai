import { useEffect, useState, useCallback, useRef } from 'react'
import { Upload, FileText, Trash2, Play, CheckCircle, XCircle, Clock, Loader2, AlertCircle } from 'lucide-react'
import { documents } from '../lib/api'
import type { DocumentInfo } from '../lib/api'
import { dashboardWS } from '../lib/websocket'

export default function MyDocuments() {
    const [docs, setDocs] = useState<DocumentInfo[]>([])
    const [counts, setCounts] = useState({ total: 0, pending: 0, processing: 0, ready: 0, failed: 0 })
    const [loading, setLoading] = useState(true)
    const [uploading, setUploading] = useState(false)
    const [selected, setSelected] = useState<Set<string>>(new Set())
    const [dragOver, setDragOver] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [processingIds, setProcessingIds] = useState<Set<string>>(new Set()) // Track docs being processed
    const fileInputRef = useRef<HTMLInputElement>(null)

    const fetchDocuments = useCallback(async () => {
        try {
            const data = await documents.list()
            setDocs(data.documents)
            setCounts(data.counts)
            setError(null)
        } catch (e) {
            console.error('Documents API error:', e)
            // Show more details for debugging
            const msg = e instanceof Error ? e.message : 'Failed to load documents'
            setError(`${msg} — Check browser console for details`)
        } finally {
            setLoading(false)
        }
    }, [])

    useEffect(() => {
        fetchDocuments()

        // Subscribe to document status changes via WebSocket
        const unsub = dashboardWS.on('document.status_change', (payload: unknown) => {
            const { document_id, status } = payload as { document_id: string; status: string }
            setDocs(prev => prev.map(doc =>
                doc.document_id === document_id ? { ...doc, status: status as DocumentInfo['status'] } : doc
            ))
        })

        // Poll for updates every 10s (backup for WebSocket)
        const poll = setInterval(fetchDocuments, 10000)

        return () => {
            unsub()
            clearInterval(poll)
        }
    }, [fetchDocuments])

    const handleFileSelect = async (files: FileList | null) => {
        if (!files || files.length === 0) return

        setUploading(true)
        setError(null)

        for (const file of Array.from(files)) {
            try {
                await documents.upload(file)
            } catch (e) {
                setError(e instanceof Error ? e.message : `Failed to upload ${file.name}`)
            }
        }

        setUploading(false)
        fetchDocuments()
    }

    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault()
        setDragOver(false)
        handleFileSelect(e.dataTransfer.files)
    }

    const handleProcess = async (docId: string) => {
        // Immediately mark as processing for visual feedback
        setProcessingIds(prev => new Set(prev).add(docId))
        // Optimistically update the doc status in UI
        setDocs(prev => prev.map(doc =>
            doc.document_id === docId ? { ...doc, status: 'processing' as const } : doc
        ))

        try {
            await documents.process(docId)
            fetchDocuments()
        } catch (e) {
            setError(e instanceof Error ? e.message : 'Failed to process document')
            // Revert optimistic update on error
            setDocs(prev => prev.map(doc =>
                doc.document_id === docId ? { ...doc, status: 'pending' as const } : doc
            ))
        } finally {
            setProcessingIds(prev => {
                const next = new Set(prev)
                next.delete(docId)
                return next
            })
        }
    }

    const handleProcessAll = async () => {
        // Mark all pending docs as processing for visual feedback
        const pendingIds = docs.filter(d => d.status === 'pending').map(d => d.document_id)
        setProcessingIds(prev => new Set([...prev, ...pendingIds]))
        // Optimistically update all pending docs to processing
        setDocs(prev => prev.map(doc =>
            doc.status === 'pending' ? { ...doc, status: 'processing' as const } : doc
        ))

        try {
            const result = await documents.processAll()
            setError(null)
            if (result.queued_count > 0) {
                fetchDocuments()
            }
        } catch (e) {
            setError(e instanceof Error ? e.message : 'Failed to process documents')
            // Revert optimistic updates on error
            setDocs(prev => prev.map(doc =>
                pendingIds.includes(doc.document_id) ? { ...doc, status: 'pending' as const } : doc
            ))
        } finally {
            setProcessingIds(prev => {
                const next = new Set(prev)
                pendingIds.forEach(id => next.delete(id))
                return next
            })
        }
    }

    const handleDelete = async (docId: string) => {
        if (!confirm('Delete this document? This cannot be undone.')) return

        try {
            await documents.delete(docId)
            setSelected(prev => {
                const next = new Set(prev)
                next.delete(docId)
                return next
            })
            fetchDocuments()
        } catch (e) {
            setError(e instanceof Error ? e.message : 'Failed to delete document')
        }
    }

    const handleDeleteSelected = async () => {
        if (selected.size === 0) return
        if (!confirm(`Delete ${selected.size} document(s)? This cannot be undone.`)) return

        try {
            await documents.deleteBatch(Array.from(selected))
            setSelected(new Set())
            fetchDocuments()
        } catch (e) {
            setError(e instanceof Error ? e.message : 'Failed to delete documents')
        }
    }

    const toggleSelect = (docId: string) => {
        setSelected(prev => {
            const next = new Set(prev)
            if (next.has(docId)) next.delete(docId)
            else next.add(docId)
            return next
        })
    }

    const toggleSelectAll = () => {
        if (selected.size === docs.length) {
            setSelected(new Set())
        } else {
            setSelected(new Set(docs.map(d => d.document_id)))
        }
    }

    const formatFileSize = (bytes: number): string => {
        if (bytes < 1024) return `${bytes} B`
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
    }

    const StatusBadge = ({ status }: { status: DocumentInfo['status'] }) => {
        const config = {
            pending: { icon: Clock, color: 'var(--color-text-muted)', bg: 'var(--color-bg-elevated)', label: 'Pending' },
            processing: { icon: Loader2, color: 'var(--color-accent)', bg: 'rgba(59, 130, 246, 0.1)', label: 'Processing' },
            ready: { icon: CheckCircle, color: 'var(--color-success)', bg: 'rgba(34, 197, 94, 0.1)', label: 'Ready' },
            failed: { icon: XCircle, color: 'var(--color-error)', bg: 'rgba(239, 68, 68, 0.1)', label: 'Failed' },
        }
        const { icon: Icon, color, bg, label } = config[status]

        return (
            <span
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium"
                style={{ color, backgroundColor: bg }}
            >
                <Icon size={12} className={status === 'processing' ? 'animate-spin' : ''} />
                {label}
            </span>
        )
    }

    if (loading) {
        return (
            <div className="flex items-center justify-center h-64">
                <Loader2 className="animate-spin" size={32} style={{ color: 'var(--color-accent)' }} />
            </div>
        )
    }

    return (
        <div className="space-y-4 h-full flex flex-col">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-lg font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                        My Documents
                    </h1>
                    <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                        {counts.total} document{counts.total !== 1 ? 's' : ''} &bull;{' '}
                        {counts.ready} ready &bull; {counts.pending} pending &bull; {counts.processing} processing
                    </p>
                </div>
                <button
                    onClick={handleProcessAll}
                    disabled={counts.pending === 0 || counts.processing > 0}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium cursor-pointer disabled:opacity-40"
                    style={{ background: 'var(--color-accent)', color: '#fff' }}
                >
                    <Play size={14} />
                    {counts.processing > 0 ? `Processing (${counts.processing})` : `Process All (${counts.pending})`}
                </button>
            </div>

            {/* Error Alert */}
            {error && (
                <div
                    className="flex items-center gap-2 p-3 rounded-lg text-xs"
                    style={{ background: 'rgba(239, 68, 68, 0.1)', color: 'var(--color-error)' }}
                >
                    <AlertCircle size={14} />
                    {error}
                    <button onClick={() => setError(null)} className="ml-auto cursor-pointer">×</button>
                </div>
            )}

            {/* Upload Zone */}
            <div
                className={`border-2 border-dashed rounded-lg p-6 text-center transition-colors cursor-pointer ${dragOver ? 'border-blue-500 bg-blue-500/5' : ''}`}
                style={{
                    borderColor: dragOver ? 'var(--color-accent)' : 'var(--color-border)',
                    background: dragOver ? 'rgba(59, 130, 246, 0.05)' : 'var(--color-bg-elevated)',
                }}
                onClick={() => fileInputRef.current?.click()}
                onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}
            >
                <input
                    ref={fileInputRef}
                    type="file"
                    accept=".pdf,.md,.docx"
                    multiple
                    className="hidden"
                    onChange={(e) => handleFileSelect(e.target.files)}
                />
                {uploading ? (
                    <div className="flex items-center justify-center gap-2">
                        <Loader2 className="animate-spin" size={20} style={{ color: 'var(--color-accent)' }} />
                        <span style={{ color: 'var(--color-text-secondary)' }}>Uploading...</span>
                    </div>
                ) : (
                    <>
                        <Upload size={24} style={{ color: 'var(--color-text-muted)' }} className="mx-auto mb-2" />
                        <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                            Drop files here or click to browse
                        </p>
                        <p className="text-xs mt-1" style={{ color: 'var(--color-text-muted)' }}>
                            PDF, MD, DOCX (max 50MB per file)
                        </p>
                    </>
                )}
            </div>

            {/* Selection Bar */}
            {docs.length > 0 && (
                <div className="flex items-center justify-between">
                    <label className="flex items-center gap-2 text-xs cursor-pointer" style={{ color: 'var(--color-text-secondary)' }}>
                        <input
                            type="checkbox"
                            checked={selected.size === docs.length && docs.length > 0}
                            onChange={toggleSelectAll}
                            className="rounded"
                        />
                        Select All
                    </label>
                    {selected.size > 0 && (
                        <button
                            onClick={handleDeleteSelected}
                            className="flex items-center gap-1 px-2 py-1 rounded text-xs cursor-pointer"
                            style={{ color: 'var(--color-error)' }}
                        >
                            <Trash2 size={12} /> Delete Selected ({selected.size})
                        </button>
                    )}
                </div>
            )}

            {/* Document List */}
            <div className="flex-1 overflow-y-auto min-h-0 space-y-2">
                {docs.length === 0 ? (
                    <div className="text-center py-12" style={{ color: 'var(--color-text-muted)' }}>
                        <FileText size={48} className="mx-auto mb-3 opacity-50" />
                        <p>No documents yet</p>
                        <p className="text-xs mt-1">Upload files to get started</p>
                    </div>
                ) : (
                    docs.map((doc) => (
                        <div
                            key={doc.document_id}
                            className="flex items-center gap-3 p-3 rounded-lg"
                            style={{ background: 'var(--color-bg-elevated)', border: '1px solid var(--color-border-subtle)' }}
                        >
                            <input
                                type="checkbox"
                                checked={selected.has(doc.document_id)}
                                onChange={() => toggleSelect(doc.document_id)}
                                className="rounded"
                            />
                            <FileText size={20} style={{ color: 'var(--color-text-muted)' }} />
                            <div className="flex-1 min-w-0">
                                <p
                                    className="text-sm font-medium truncate"
                                    style={{ color: 'var(--color-text-primary)' }}
                                    title={doc.filename}
                                >
                                    {doc.filename}
                                </p>
                                <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                                    {doc.upload_date} &bull; {formatFileSize(doc.file_size)}
                                </p>
                            </div>
                            <StatusBadge status={doc.status} />
                            <div className="flex items-center gap-1">
                                {doc.status === 'pending' && (
                                    <button
                                        onClick={() => handleProcess(doc.document_id)}
                                        disabled={processingIds.has(doc.document_id)}
                                        className="p-1.5 rounded hover:bg-blue-500/10 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                                        style={{ color: 'var(--color-accent)' }}
                                        title={processingIds.has(doc.document_id) ? "Processing..." : "Process"}
                                    >
                                        {processingIds.has(doc.document_id) ? (
                                            <Loader2 size={14} className="animate-spin" />
                                        ) : (
                                            <Play size={14} />
                                        )}
                                    </button>
                                )}
                                {doc.status === 'failed' && doc.error_message && (
                                    <button
                                        className="p-1.5 rounded cursor-pointer"
                                        style={{ color: 'var(--color-error)' }}
                                        title={doc.error_message}
                                    >
                                        <AlertCircle size={14} />
                                    </button>
                                )}
                                <button
                                    onClick={() => handleDelete(doc.document_id)}
                                    className="p-1.5 rounded hover:bg-red-500/10 cursor-pointer"
                                    style={{ color: 'var(--color-text-muted)' }}
                                    title="Delete"
                                >
                                    <Trash2 size={14} />
                                </button>
                            </div>
                        </div>
                    ))
                )}
            </div>
        </div>
    )
}
